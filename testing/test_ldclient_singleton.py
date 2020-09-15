import ldclient
from ldclient import _reset_client
from ldclient.config import Config
from testing.http_util import start_server, BasicResponse
from testing.stub_util import make_put_event, stream_content
from testing.sync_util import wait_until
import json

sdk_key = 'sdk-key'

# These are end-to-end tests like test_ldclient_end_to_end, but less detailed in terms of the client's
# network behavior because what we're really testing is the singleton mechanism.

def test_set_sdk_key_before_init():
    _reset_client()
    with start_server() as stream_server:
        with stream_content(make_put_event()) as stream_handler:
            try:
                stream_server.for_path('/all', stream_handler)

                ldclient.set_config(Config(stream_uri = stream_server.uri, send_events = False))
                ldclient.set_sdk_key(sdk_key)
                wait_until(ldclient.get().is_initialized, timeout=10)

                r = stream_server.await_request()
                assert r.headers['Authorization'] == sdk_key
            finally:
                _reset_client()

def test_set_sdk_key_after_init():
    _reset_client()
    with start_server() as stream_server:
        with stream_content(make_put_event()) as stream_handler:
            try:
                stream_server.for_path('/all', BasicResponse(401))

                ldclient.set_config(Config(stream_uri = stream_server.uri, send_events = False))
                assert ldclient.get().is_initialized() is False

                r = stream_server.await_request()
                assert r.headers['Authorization'] == ''

                stream_server.for_path('/all', stream_handler)

                ldclient.set_sdk_key(sdk_key)
                wait_until(ldclient.get().is_initialized, timeout=30)

                r = stream_server.await_request()
                assert r.headers['Authorization'] == sdk_key
            finally:
                _reset_client()

def test_set_config():
    _reset_client()
    with start_server() as stream_server:
        with stream_content(make_put_event()) as stream_handler:
            try:
                stream_server.for_path('/all', stream_handler)

                ldclient.set_config(Config(offline=True))
                assert ldclient.get().is_offline() is True

                ldclient.set_config(Config(sdk_key = sdk_key, stream_uri = stream_server.uri, send_events = False))
                assert ldclient.get().is_offline() is False
                wait_until(ldclient.get().is_initialized, timeout=10)

                r = stream_server.await_request()
                assert r.headers['Authorization'] == sdk_key
            finally:
                _reset_client()