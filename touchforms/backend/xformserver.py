import sys
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
from SocketServer import ThreadingMixIn
import threading
import logging
import xformplayer
import touchcare
import java.lang
import time
import urllib2
from optparse import OptionParser
from datetime import datetime, timedelta
import settings

from setup import init_classpath
init_classpath()
import com.xhaus.jyson.JysonCodec as json
from xcp import TouchFormsException, InvalidRequestException

logger = logging.getLogger('formplayer.xformserver')
DEFAULT_PORT = 4444
DEFAULT_STALE_WINDOW = 3. #hours

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

class XFormHTTPGateway(threading.Thread):
    def __init__(self, port, stale_window, extensions=[]):
        threading.Thread.__init__(self)
        self.server = ThreadingHTTPServer(('', port), XFormRequestHandler)
        self.server.extensions = extensions
        self.server.default_stale_window = stale_window

    def run(self):
        self.server.serve_forever()

    def terminate(self):
        self.server.shutdown()

class XFormRequestHandler(BaseHTTPRequestHandler):

    error_content_type = "text/json"

    def do_POST(self):
        if 'content-length' in self.headers.dict:
            length = int(self.headers.dict['content-length'])
        else:
            logger.warn('content length required')
            self.send_error(400, 'content length required for post')
            return

        if 'content-type' not in self.headers.dict or self.headers.dict['content-type'] != 'text/json':
            logger.warn('content type missing or non-json')

        body = self.rfile.read(length)
        try:
            logger.debug('received: [%s]' % body)
            data_in = json.loads(body)
        except:
            logger.warn('content does not parse')
            self.send_error(400, 'content does not parse as valid json')
            return

        try:
            data_out = handle_request(data_in, self.server)
            reply = json.dumps(data_out)
        except InvalidRequestException, e:
            self.send_error(400, str(e))
            return
        except (Exception, java.lang.Exception), e:
            msg = ''
            if isinstance(e, java.lang.Exception):
                e.printStackTrace()  # todo: log the java stacktrace
            elif isinstance(e, urllib2.HTTPError):
                if e.headers.get("content-type", "") == "text/plain":
                    msg = e.read()

            info = sys.exc_info()

            self.send_error(
                500,
                u'internal error handling request: %s: %s%s' % (
                    type(e), unicode(e), u": %s" % msg if msg else ""),
                unicode(info[0]),
                msg if msg else None,
            )
            return

        logger.debug('returned: [%s]' % reply)

        self.send_response(200)
        self.send_header('Content-Type', 'text/json; charset=utf-8')
        self.cross_origin_header()
        self.end_headers()
        self.wfile.write(reply.encode('utf-8'))
        
    def send_error(self, code, message=None, error_type=None, human_readable_message=None):
        """
        Override send_error to always return JSON.
        """
        # copied and pasted lots of this from the base class
        # but had to override due to html escaping messing up
        # the json format of the message
        try:
            short, long = self.responses[code]
        except KeyError:
            short, long = '???', '???'
        if message is None:
            message = short
        if human_readable_message is None:
            human_readable_message = message
        explain = long
        logger.exception("Status Code: %d, Message %s" % (code, message))
        content = json.dumps({'status': 'error',
                              'error_type': error_type,
                              'code': code, 
                              'message': message,
                              'human_readable_message': human_readable_message,
                              'explain': explain})

        # if this is more than one line it messes up the response content
        message = message.split("\n")[0] if message else ""
        self.send_response(code, message.encode("ascii", "xmlcharrefreplace"))
        self.send_header("Content-Type", self.error_content_type)
        self.cross_origin_header()
        self.send_header('Connection', 'close')
        self.end_headers()
        if self.command != 'HEAD' and code >= 200 and code not in (204, 304):
            self.wfile.write(content.encode("utf-8"))

    # we don't support GET but still want to allow heartbeat responses via cross-origin
    def do_GET(self):
        self.send_response(405, 'method not allowed')
        self.cross_origin_header()
        self.end_headers()

    def cross_origin_header(self):
        if settings.ALLOW_CROSS_ORIGIN:
            self.send_header('Access-Control-Allow-Origin', '*')


def ensure_required_params(params, action, content):
    for param in params:
        if param not in content:
            raise InvalidRequestException("'%s' is required for action: %s" % (param, action))


def handle_request(content, server):
    ensure_required_params(['action'], 'All actions', content)

    action = content['action']
    logger.info('Received action %s' % action)
    nav_mode = content.get('nav', 'prompt')
    try:
        if action != xformplayer.Actions.NEW_FORM and action not in touchcare.SUPPORTED_ACTIONS:
            ensure_required_params(['session-id'], action, content)

        if action == xformplayer.Actions.NEW_FORM:
            form_fields = {'form-name': 'uid', 'form-content': 'raw', 'form-url': 'url'}
            form_spec = None
            for k, v in form_fields.iteritems():
                try:
                    form_spec = (v, content[k])
                    break
                except KeyError:
                    pass
            if not form_spec:
                return {'error': 'form specification required (form-name, form-content, or form-url)'}

            if 'instance-content' in content:
                inst_spec = ('raw', content['instance-content'])
            else:
                inst_spec = None

            session_data = content.get("session-data", {})
            return xformplayer.open_form(form_spec, inst_spec, **{
                    'init_lang': content.get('lang'),
                    'extensions': server.extensions,
                    'session_data': session_data,
                    'nav_mode': nav_mode,
                    'api_auth': content.get('hq_auth'),
                    'staleness_window': content.get('staleness_window', server.default_stale_window),
                })

        elif action == xformplayer.Actions.ANSWER:
            ensure_required_params(['answer'], action, content)
            return xformplayer.answer_question(content['session-id'], content['answer'], content.get('ix'))

        #sequential (old-style) repeats only
        elif action == xformplayer.Actions.ADD_REPEAT:
            return xformplayer.new_repetition(content['session-id'])

        elif action == xformplayer.Actions.NEXT:
            return xformplayer.skip_next(content['session-id'])

        elif action == xformplayer.Actions.BACK:
            return xformplayer.go_back(content['session-id'])

        elif action == xformplayer.Actions.CURRENT:
            override_state = None
            # override api_auth with the current auth to avoid issues with expired django sessions
            # when editing saved forms
            hq_auth = content.get('hq_auth')
            if hq_auth:
                override_state = {
                    'api_auth': hq_auth,
                }
            return xformplayer.current_question(content['session-id'], override_state=override_state)

        elif action == xformplayer.Actions.HEARTBEAT:
            return xformplayer.heartbeat(content['session-id'])

        elif action == xformplayer.Actions.EDIT_REPEAT:
            ensure_required_params(['ix'], action, content)
            return xformplayer.edit_repeat(content['session-id'], content['ix'])

        elif action == xformplayer.Actions.NEW_REPEAT:
            return xformplayer.new_repeat(content['session-id'], content.get('ix'))
        elif action == xformplayer.Actions.DELETE_REPEAT:
            ensure_required_params(['ix'], action, content)
            return xformplayer.delete_repeat(content['session-id'], content['ix'], content.get('form_ix'))
        elif action == xformplayer.Actions.SUBMIT_ALL:
            return xformplayer.submit_form(content['session-id'], content.get('answers', []), content.get('prevalidated', False))
        elif action == xformplayer.Actions.SET_LANG:
            ensure_required_params(['lang'], action, content)
            return xformplayer.set_locale(content['session-id'], content['lang'])
        elif action == xformplayer.Actions.PURGE_STALE:
            ensure_required_params(['window'], action, content)
            return xformplayer.purge(content['window'])
        elif action in touchcare.SUPPORTED_ACTIONS:
            return touchcare.handle_request(content, server)
        elif action == xformplayer.Actions.GET_INSTANCE:
            xfsess = xformplayer.global_state.get_session(content['session-id'])
            return {"output": xfsess.output()}

        elif action == 'get-instance-xml':
            if 'session-id' not in content:
                return {'error': 'session id required'}
            xfsess = xformplayer.global_state.get_instance_xml(content['session-id'])
            print xfsess.prettify1()
            return {"output": xfsess.prettify1()}

        else:
            raise InvalidRequestException("Unrecognized action: %s" % action)
    
    except xformplayer.NoSuchSession:
        return {'error': 'invalid session id'}
    except xformplayer.SequencingException:
        return {'error': 'session is locked by another request'}

class Purger(threading.Thread):
    def __init__(self, purge_freq=1.):
        threading.Thread.__init__(self)
        self.purge_freq = timedelta(minutes=purge_freq)

        self.last_purge = None
        self.up = True

    def run(self):
        self.update()
        while self.up:
            if self.purge_due():
                self.update()
                result = xformplayer.purge()
                logger.info('purging sessions: ' + str(result))

            time.sleep(0.1)

    def purge_due(self):
        if self.last_purge == None:
            return True
        elif datetime.utcnow() - self.last_purge > self.purge_freq:
            return True
        elif datetime.utcnow() < self.last_purge:
            return True
        return False

    def update(self):
        self.last_purge = datetime.utcnow()

    def terminate(self):
        self.up = False

def init_gui():
    try:
        import GUI
        ctx = GUI()
        ctx.load()
        return ctx
    except ImportError:
        # not in offline mode
        class GUIStub(object):
            def __getattr__(self, name):
                return lambda _self: None
        return GUIStub()

def main(port=DEFAULT_PORT, stale_window=DEFAULT_STALE_WINDOW, offline=False):
    if offline:
        settings.ALLOW_CROSS_ORIGIN = True
        settings.PERSIST_SESSIONS = False
    ext_mod = settings.EXTENSION_MODULES

    xformplayer._init(init_gui())

    gw = XFormHTTPGateway(port, stale_window, ext_mod)
    gw.start()
    logger.info('started server on port %d' % port)

    purger = Purger()
    purger.start()
    logger.info('purging sessions inactive for more than %s hours' % stale_window)

    if settings.HACKS_MODE:
        logger.info('hacks mode is enabled, and you should feel bad about that')

    try:
        while True:
            time.sleep(.01) #yield thread
    except KeyboardInterrupt:
        purger.terminate()

        #note: the keyboardinterrupt event doesn't seem to be triggered in
        #jython, nor does jython2.5 support the httpserver 'shutdown' method
        logger.info('interrupted; shutting down...')
        gw.terminate()

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option('-p', '--port', dest='port', type='int', default=DEFAULT_PORT)
    parser.add_option('--stale', dest='stale_window', type='float', default=DEFAULT_STALE_WINDOW,
                      help='length of inactivity before a form session is discarded (hours)')

    (options, args) = parser.parse_args()

    main(
        port=options.port,
        stale_window=options.stale_window
    )
