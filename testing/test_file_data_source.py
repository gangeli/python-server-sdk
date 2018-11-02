import json
import os
import pytest
import six
import tempfile
import threading
import time

from ldclient.client import LDClient
from ldclient.config import Config
from ldclient.feature_store import InMemoryFeatureStore
from ldclient.file_data_source import FileDataSource
from ldclient.versioned_data_kind import FEATURES, SEGMENTS


all_flag_keys = [ 'flag1', 'flag2' ]
all_properties_json = '''
  {
    "flags": {
      "flag1": {
        "key": "flag1",
        "on": true,
        "fallthrough": {
          "variation": 2
        },
        "variations": [ "fall", "off", "on" ]
      }
    },
    "flagValues": {
      "flag2": "value2"
    },
    "segments": {
      "seg1": {
        "key": "seg1",
        "include": ["user1"]
      }
    }
  }
'''

all_properties_yaml = '''
---
flags:
  flag1:
    key: flag1
    "on": true
flagValues:
  flag2: value2
segments:
  seg1:
    key: seg1
    include: ["user1"]
'''

flag_only_json = '''
  {
    "flags": {
      "flag1": {
        "key": "flag1",
        "on": true,
        "fallthrough": {
          "variation": 2
        },
        "variations": [ "fall", "off", "on" ]
      }
    }
  }
'''

segment_only_json = '''
  {
    "segments": {
      "seg1": {
        "key": "seg1",
        "include": ["user1"]
      }
    }
  }
'''

data_source = None
store = None
ready = None


def setup_function():
    global data_source, store, ready
    store = InMemoryFeatureStore()
    ready = threading.Event()

def teardown_function():
    if data_source is not None:
        data_source.stop()

def make_temp_file(content):
    f, path = tempfile.mkstemp()
    os.write(f, six.b(content))
    os.close(f)
    return path

def replace_file(path, content):
    with open(path, 'w') as f:
        f.write(content)

def test_does_not_load_data_prior_to_start():
    path = make_temp_file('{"flagValues":{"key":"value"}}')
    try:
        data_source = FileDataSource.factory(paths = path)(Config(), store, ready)
        assert ready.is_set() is False
        assert data_source.initialized() is False
        assert store.initialized is False
    finally:
        os.remove(path)

def test_loads_flags_on_start_from_json():
    path = make_temp_file(all_properties_json)
    try:
        data_source = FileDataSource.factory(paths = path)(Config(), store, ready)
        data_source.start()
        assert store.initialized is True
        assert sorted(list(store.all(FEATURES, lambda x: x).keys())) == all_flag_keys
    finally:
        os.remove(path)

def test_loads_flags_on_start_from_yaml():
    path = make_temp_file(all_properties_yaml)
    try:
        data_source = FileDataSource.factory(paths = path)(Config(), store, ready)
        data_source.start()
        assert store.initialized is True
        assert sorted(list(store.all(FEATURES, lambda x: x).keys())) == all_flag_keys
    finally:
        os.remove(path)

def test_sets_ready_event_and_initialized_on_successful_load():
    path = make_temp_file(all_properties_json)
    try:
        data_source = FileDataSource.factory(paths = path)(Config(), store, ready)
        data_source.start()
        assert data_source.initialized() is True
        assert ready.is_set() is True
    finally:
        os.remove(path)

def test_sets_ready_event_and_does_not_set_initialized_on_unsuccessful_load():
    bad_file_path = 'no-such-file'
    data_source = FileDataSource.factory(paths = bad_file_path)(Config(), store, ready)
    data_source.start()
    assert data_source.initialized() is False
    assert ready.is_set() is True

def test_can_load_multiple_files():
    path1 = make_temp_file(flag_only_json)
    path2 = make_temp_file(segment_only_json)
    try:
        data_source = FileDataSource.factory(paths = [ path1, path2 ])(Config(), store, ready)
        data_source.start()
        assert len(store.all(FEATURES, lambda x: x)) == 1
        assert len(store.all(SEGMENTS, lambda x: x)) == 1
    finally:
        os.remove(path1)
        os.remove(path2)

def test_does_not_allow_duplicate_keys():
    path1 = make_temp_file(flag_only_json)
    path2 = make_temp_file(flag_only_json)
    try:
        data_source = FileDataSource.factory(paths = [ path1, path2 ])(Config(), store, ready)
        data_source.start()
        assert len(store.all(FEATURES, lambda x: x)) == 0
    finally:
        os.remove(path1)
        os.remove(path2)

def test_does_not_reload_modified_file_if_auto_update_is_off():
    path = make_temp_file(flag_only_json)
    try:
        data_source = FileDataSource.factory(paths = path)(Config(), store, ready)
        data_source.start()
        assert len(store.all(SEGMENTS, lambda x: x)) == 0
        time.sleep(0.5)
        replace_file(path, segment_only_json)
        time.sleep(0.5)
        assert len(store.all(SEGMENTS, lambda x: x)) == 0
    finally:
        os.remove(path)

def do_auto_update_test(options):
    path = make_temp_file(flag_only_json)
    options['paths'] = path
    try:
        data_source = FileDataSource.factory(**options)(Config(), store, ready)
        data_source.start()
        assert len(store.all(SEGMENTS, lambda x: x)) == 0
        time.sleep(0.5)
        replace_file(path, segment_only_json)
        print("*** modified file %s" % path)
        deadline = time.time() + 10
        while time.time() < deadline:
            time.sleep(0.1)
            if len(store.all(SEGMENTS, lambda x: x)) == 1:
                return
            print("*** checked")
        assert False, "Flags were not reloaded after 10 seconds"
    finally:
        os.remove(path)

def test_reloads_modified_file_if_auto_update_is_on():
    do_auto_update_test({ 'auto_update': True })

def test_reloads_modified_file_in_polling_mode():
    do_auto_update_test({ 'auto_update': True, 'force_polling': True, 'poll_interval': 0.1 })

def test_evaluates_full_flag_with_client_as_expected():
    path = make_temp_file(all_properties_json)
    try:
        data_source = FileDataSource.factory(paths = path)
        client = LDClient(config=Config(update_processor_class = data_source, send_events = False))
        value = client.variation('flag1', { 'key': 'user' }, '')
        assert value == 'on'
    finally:
        os.remove(path)
        if client is not None:
            client.close()

def test_evaluates_simplified_flag_with_client_as_expected():
    path = make_temp_file(all_properties_json)
    try:
        data_source = FileDataSource.factory(paths = path)
        client = LDClient(config=Config(update_processor_class = data_source, send_events = False))
        value = client.variation('flag2', { 'key': 'user' }, '')
        assert value == 'value2'
    finally:
        os.remove(path)
        if client is not None:
            client.close()
