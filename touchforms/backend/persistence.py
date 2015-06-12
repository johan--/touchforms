from __future__ import with_statement
import tempfile
from gettext import gettext as _
import os
from xcp import EmptyCacheFileException
import settings
from com.xhaus.jyson import JSONDecodeError
import com.xhaus.jyson.JysonCodec as json
from java.lang import Class
from java.sql  import DriverManager, SQLException
import classPathHacker
from com.ziclix.python.sql import zxJDBC

def persist(sess):
    sess_id = sess.uuid
    state = sess.session_state()
    timeout = sess.staleness_window
    cache_set(sess_id, state, timeout)

def restore(sess_id, factory, override_state=None):
    try:
        state = cache_get(sess_id)
    except KeyError:
        return None

    state['uuid'] = sess_id
    if override_state:
        state.update(override_state)
    return factory(**state)

# TODO integrate with real caching framework (django ideally)
def cache_set(key, value, timeout):
    with open(cache_path(key), 'w') as f:
        f.write(json.dumps(value).encode('utf8'))

# TODO integrate with real caching framework (django ideally)
def cache_get(key):
    try:
        with open(cache_path(key)) as f:
            return json.loads(f.read().decode('utf8'))
    except IOError:
        raise KeyError
    except JSONDecodeError:
        raise EmptyCacheFileException(_(
            u"Unfortunately an error has occurred on the server and your form cannot be saved. "
            u"Please take note of the questions you have filled out so far, then refresh this page and enter them again. "
            u"If this problem persists, please report an issue."
        ))


def cache_del(key):
    raise RuntimeError('not implemented')

def cache_path(key):
    # todo: make this use something other than the filesystem
    persistence_dir = settings.PERSISTENCE_DIRECTORY or tempfile.gettempdir()
    if not os.path.exists(persistence_dir):
        os.makedirs(persistence_dir)
    return os.path.join(persistence_dir, 'tfsess-%s' % key)


def sqlite_get_connection(database):

    params = {
        'url': 'jdbc:sqlite:/tmp/%s' % database,
    }

    try:
        # try to connect regularly

        conn = zxJDBC.connectx("org.sqlite.javax.SQLiteConnectionPoolDataSource", **params)

    except:
        # else fall back to this workaround (we expect to do this)

        try:
            jarloader = classPathHacker.classPathHacker()
            a = jarloader.addFile(settings.SQLITE_JDBC_JAR)
            conn = zxJDBC.connectx("org.sqlite.javax.SQLiteConnectionPoolDataSource", **params)
        except zxJDBC.DatabaseError, msg:
            print msg


    return conn


