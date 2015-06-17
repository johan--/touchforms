import urllib
from urllib2 import HTTPError, URLError
import com.xhaus.jyson.JysonCodec as json
import logging
from datetime import datetime
from copy import copy

import settings

from java.lang import Throwable
from org.javarosa.core.model.instance import InstanceInitializationFactory
from org.javarosa.core.services.storage import IStorageUtilityIndexed
from org.javarosa.core.services.storage import IStorageIterator
from org.commcare.cases.instance import CaseInstanceTreeElement
from org.commcare.cases.ledger.instance import LedgerInstanceTreeElement
from org.commcare.cases.model import Case
from org.commcare.cases.ledger import Ledger
from org.commcare.util import CommCareSession
from org.javarosa.xml import TreeElementParser

from org.javarosa.xpath.expr import XPathFuncExpr
from org.javarosa.xpath import XPathParseTool, XPathException
from org.javarosa.xpath.parser import XPathSyntaxException
from org.javarosa.core.model.condition import EvaluationContext
from org.javarosa.core.model.instance import ExternalDataInstance
from org.commcare.api.persistence import UserDatabaseHelper

from java.util import Hashtable

from org.kxml2.io import KXmlParser
import org.python.core.PyList as PyList
from util import to_vect, to_jdate, to_hashtable, to_input_stream, query_factory
from xcp import TouchFormsUnauthorized, TouchcareInvalidXPath
from persistence import sqlite_get_connection
from org.javarosa.core.services.storage import IStorageUtilityIndexed, IStorageIterator
from persistence import sqlite_get_connection
import settings
from org.javarosa.core.services.storage import Persistable
from org.javarosa.core.services.storage import IMetaData
from org.commcare.api.util import TableUtil
import java.util.Iterator
import java.util.Map
from org.commcare.cases.model import Case
import com.xhaus.jyson.JysonCodec as json
import com.google.gson.Gson as Gson
import com.google.gson.GsonBuilder as GsonBuilder

def execute_func(database_name, exec_sql):
    conn = sqlite_get_connection(database_name)
    cursor = conn.cursor()
    cursor.execute(exec_sql)
    cursor.close()
    conn.commit()
    conn.close()

def execute_func_params(database_name, exec_sql, exec_params):
    conn = sqlite_get_connection(database_name)
    cursor = conn.cursor()
    cursor.execute(exec_sql, exec_params)
    cursor.close()
    conn.commit()
    conn.close()

def build_insert_statement(table_name, values):
    start_statement = "INSERT INTO %s " % table_name + " ("
    end_statement = "("
    it = values.entrySet().iterator()
    params = []
    while it.hasNext():
        pair = it.next()
        start_statement += str(pair.getKey()) + ", "
        end_statement += " ? ,"
        params.append(pair.getValue())

    start_statement = start_statement[:-2] + ") VALUES "
    end_statement = end_statement[:-1] + ")"

    ret = start_statement + end_statement

    return ret, params

class StaticIterator(IStorageIterator):
    def __init__(self, ids):
        self.ids = ids
        self.i = 0

    def hasMore(self):
        return self.i < len(self.ids)

    def nextID(self):
        id = self.ids[self.i]
        self.i += 1
        return id


class SQLiteCaseDatabase(IStorageUtilityIndexed):
    # for now only do this for cases
    def __init__(self, host, domain, auth, additional_filters=None, preload=False,
                 form_context=None, user_id=None):
        self.user_id = user_id
        self.database_name = '%s-casedb.db' % user_id
        self.additional_filters = additional_filters or {}
        self.drop_table()
        self.create_table()
        self.query_func = query_factory(host, domain, auth)
        self.restore()

    def restore(self):
        case_list = json.loads(query_cases(self.query_func, criteria=self.additional_filters))
        for c in case_list:
            self.write(case_from_json(c))

    def write(self, case):
        #if p.getID() != -1:
        #    self.update(p.getID(), p)
        #    return

        ins_sql = "INSERT INTO TFCase (case_id, case_type, case_status, commcare_sql_record," \
                  "user_id, date_modified, closed, attachments, indices, case_name) " \
                      "VALUES (?, ?, ?, ? , ?, ?, ?, ?, ?, ?)"

        builder = GsonBuilder()
        gson = builder.create()

        ins_params = [case.getCaseId(), case.getMetaData(Case.INDEX_CASE_TYPE),
                      case.getMetaData(Case.INDEX_CASE_STATUS), gson.toJson(case.getProperties()),
                      case.getUserId(), case.getLastModified(), case.isClosed(),
                      gson.toJson(case.getAttachments()), gson.toJson(case.getIndices()), case.getName()]
        execute_func_params(self.database_name, ins_sql, ins_params)

    def read(self, id):
        sel_sql = "SELECT * FROM TFCase WHERE commcare_sql_id = ?"
        sel_params = [id]
        conn = sqlite_get_connection(self.database_name)
        cursor = conn.cursor()
        cursor.execute(sel_sql, sel_params)
        row = cursor.fetchone()
        if row is not None:
            case = self.case_from_row(row)
        else:
            case = None

        cursor.close()

        conn.commit()
        conn.close()
        return case

    def getIDsForValue(self, fieldname, value):
        sel_sql = "SELECT case_id FROM TFCase WHERE %s = ?" % fieldname
        sel_params = [value]
        conn = sqlite_get_connection(self.database_name)
        cursor = conn.cursor()
        cursor.execute(sel_sql, sel_params)
        rows = cursor.fetchall()
        cursor.close()
        conn.commit()
        conn.close()
        return rows

    def getNumRecords(self):
        conn = sqlite_get_connection(self.database_name)
        sel_sql = "SELECT * FROM TFCase"
        cursor = conn.cursor()
        cursor.execute(sel_sql)
        rows = cursor.fetchall()
        cursor.close()
        conn.commit()
        conn.close()
        return len(rows)

    def getRecordForValue(self, fieldname, value):
        id = self.getIDsForValue(fieldname, value)[0]
        return self.read(id)

    def iterate(self):
        sel_sql = "SELECT commcare_sql_id FROM TFCase"
        conn = sqlite_get_connection(self.database_name)
        cursor = conn.cursor()
        cursor.execute(sel_sql)
        list = []
        rows = cursor.fetchall()
        for row in rows:
            list.append(row[0])
        cursor.close()
        conn.commit()
        conn.close()
        return StaticIterator(list)

    def case_from_row(self, row):
        c = Case()
        builder = GsonBuilder()
        gson = builder.create()
        #todo this is terrible
        c.setCaseId(row[1])
        c.setTypeId(row[2])
        properties = gson.fromJson(row[4], java.util.Hashtable)
        attachments = gson.fromJson(row[8], java.util.Vector)
        indices = gson.fromJson(row[9], java.util.Vector)
        c.setName(row[10])
        owner_id = row[5]
        c.setUserId(owner_id)
        c.setClosed(row[7])

        enumKey = properties.keys()

        while enumKey.hasMoreElements():
            key = enumKey.nextElement()
            val = properties.get(key)
            c.setProperty(key, val)

        iterator = indices.iterator()

        while iterator.hasNext():
            val = iterator.next()
            c.setIndex(key, val['case_type'], val['case_id'])

        iterator = attachments.iterator()

        while iterator.hasNext():
            attachment = iterator.next()
            c.setIndex(key, attachment['url'])

        return c

    def create_table(self):
        create_string = "CREATE TABLE TFCase (commcare_sql_id INTEGER PRIMARY KEY," \
                           "case_id,case_type,case_status,commcare_sql_record BLOB, user_id," \
                           "date_modified, closed, attachments BLOB, indices BLOB, case_name);"
        execute_func(self.database_name, create_string)

    def drop_table(self):
        try:
            drop_string = "DROP TABLE TFCase"
            execute_func(self.database_name, drop_string)
            print "Dropped table"
        except:
            print "Table does not exist"

logger = logging.getLogger('formplayer.touchcare')


def query_case_ids(q, criteria=None):
    criteria = copy(criteria) or {} # don't modify the passed in dict
    criteria["ids_only"] = 'true'
    query_url = '%s?%s' % (settings.CASE_API_URL, urllib.urlencode(criteria))
    print "QueryQ:, ", query_url
    return [id for id in q(query_url)]


def query_cases(q, criteria=None):
    query_url = '%s?%s' % (settings.CASE_API_URL, urllib.urlencode(criteria)) \
                    if criteria else settings.CASE_API_URL

    ret = [case_from_json(cj) for cj in q(query_url)]
    print ret
    return ret


def query_case(q, case_id):
    cases = query_cases(q, {'case_id': case_id})
    try:
        return cases[0]
    except IndexError:
        return None


def query_ledger_for_case(q, case_id):
    query_string = urllib.urlencode({'case_id': case_id})
    query_url = '%s?%s' % (settings.LEDGER_API_URL, query_string)
    return ledger_from_json(q(query_url))


def ledger_from_json(data):
    ledger = Ledger(data['entity_id'])
    for section_id, section in data['ledger'].items():
        for product_id, amount in section.items():
            ledger.setEntry(section_id, product_id, int(amount))
    return ledger


class StaticIterator(IStorageIterator):
    def __init__(self, ids):
        print "StaticIterator settings ids: ", ids
        self.ids = ids
        self.i = 0

    def hasMore(self):
        return self.i < len(self.ids)

    def nextID(self):
        id = self.ids[self.i]
        self.i += 1
        return id


class TouchformsStorageUtility(IStorageUtilityIndexed):

    def __init__(self, host, domain, auth, additional_filters=None, preload=False, form_context=None):
        print "init TouchformsStorageUtility"
        self.cached_lookups = {}
        self.form_context = form_context or {}

        if self.form_context.get('case_model', None):
            case_model = self.form_context['case_model']
            self.cached_lookups[('case-id', case_model['case_id'])] = [case_from_json(case_model)]

        self._objects = {}
        self.ids = {}
        self.fully_loaded = False  # when we've loaded every possible object
        self.query_func = query_factory(host, domain, auth)
        self.additional_filters = additional_filters or {}
        print "Touchforms preload: ", preload
        if preload:
            self.load_all_objects()
        else:
            self.load_object_ids()

    def get_object_id(self, object):
        raise NotImplementedError("subclasses must handle this")

    def fetch_object(self, object_id):
        raise NotImplementedError("subclasses must handle this")

    def load_all_objects(self):
        raise NotImplementedError("subclasses must handle this")

    def load_object_ids(self):
        raise NotImplementedError("subclasses must handle this")

    @property
    def objects(self):
        print "Getting objects"
        if self.fully_loaded:
            return self._objects
        else:
            self.load_all_objects()
        return self._objects

    def put_object(self, object):
        print "SQLite putting object: ", object
        object_id = self.get_object_id(object)
        print "SQLite putting object id: ", object_id
        self._objects[object_id] = object

    def read(self, record_id):
        logger.debug('read record %s' % record_id)
        print "Reading record, ", record_id
        print "ids: ", self.ids
        try:
            # record_id is an int, object_id is a guid
            object_id = self.ids[record_id]
            print "Returning id, ", object_id
        except KeyError:
            print "Key error :("
            return None
        print "returning: ", self.read_object(object_id)
        return self.read_object(object_id)

    def read_object(self, object_id):
        print "Reading object, ", object_id
        logger.debug('read object %s' % object_id)
        if object_id not in self._objects:
            self.put_object(self.fetch_object(object_id))
        try:
            return self._objects[object_id]
        except KeyError:
            raise Exception('could not find an object for id [%s]' % object_id)

    def setReadOnly(self):
        # todo: not sure why this exists. is it part of the public javarosa API?
        pass

    def getNumRecords(self):
        print "Num Records"
        return len(self.ids)

    def iterate(self):
        print "iterate tc: ", self.ids.keys()
        return StaticIterator(self.ids.keys())


class CaseDatabase(TouchformsStorageUtility):

    def get_object_id(self, case):
        print "CaseDatabase get_object_id ", case
        return case.getCaseId()

    def fetch_object(self, case_id):
        print "CaseDatabase gfet object ", case_id
        if ('case-id', case_id) in self.cached_lookups:
            return self.cached_lookups[('case-id', case_id)][0]
        return query_case(self.query_func, case_id)

    def load_all_objects(self):
        print "CaseDatabase load_all_objects"
        if self.form_context.get('cases', None):
            cases = map(lambda c: case_from_json(c), self.form_context.get('cases'))
        else:
            cases = query_cases(self.query_func,
                                criteria=self.additional_filters)
        for c in cases:
            self.put_object(c)
        # todo: the sorted() call is a hack to try and preserve order between bootstrapping
        # this with IDs versus full values. Really we should store a _next_id integer and then
        # update things as they go into self._objects inside the put_object() function.
        # http://manage.dimagi.com/default.asp?169413
        self.ids = dict(enumerate(sorted(self._objects.keys())))
        self.fully_loaded = True

    def load_object_ids(self):
        print "CaseDatabase load_object_ids, all case: ", self.form_context.get('all_case_ids', None)
        if self.form_context.get('all_case_ids', None):
            case_ids = self.form_context.get('all_case_ids')
        else:
            case_ids = query_case_ids(self.query_func, criteria=self.additional_filters)
        # todo: see note above about why sorting is necessary
        print "CaseDataBase loaded IDs, ", dict(enumerate(sorted(case_ids)))
        self.ids = dict(enumerate(sorted(case_ids)))

    def getIDsForValue(self, field_name, value):
        print "CaseDatabase getIdsForValue"
        logger.debug('case index lookup %s %s' % (field_name, value))

        if (field_name, value) not in self.cached_lookups:
            if field_name == 'case-id':
                cases = [self.read_object(value)]
            else:
                try:
                    get_val = {
                        'case-type': lambda c: c.getTypeId(),
                        'case-status': lambda c: 'closed' if c.isClosed() else 'open',
                    }[field_name]
                except KeyError:
                    # Try any unrecognized field name as a case id field.
                    # Needed for 'case-in-goal' lookup in PACT Care Plan app.
                    cases = [self.read_object(value)]
                else:
                    cases = [c for c in self.objects.values() if get_val(c) == value]

            self.cached_lookups[(field_name, value)] = cases

        cases = self.cached_lookups[(field_name, value)]
        id_map = dict((v, k) for k, v in self.ids.iteritems())
        return to_vect(id_map[c.getCaseId()] for c in cases)


def case_from_json(data):
    c = Case()
    c.setCaseId(data['case_id'])
    c.setTypeId(data['properties']['case_type'])
    c.setName(data['properties']['case_name'])
    c.setClosed(data['closed'])
    if data['properties']['date_opened']:
        c.setDateOpened(to_jdate(datetime.strptime(data['properties']['date_opened'], '%Y-%m-%dT%H:%M:%S'))) # 'Z' in fmt string omitted due to jython bug
    owner_id = data['properties']['owner_id'] or data['user_id'] or ""
    c.setUserId(owner_id) # according to clayton "there is no user_id, only owner_id"

    for k, v in data['properties'].iteritems():
        if v is not None and v != "" and k not in ['case_name', 'case_type', 'date_opened']:
            c.setProperty(k, v)

    #for k, v in data['indices'].iteritems():
    #    c.setIndex(k, v['case_type'], v['case_id'])

    #for k, v in data['attachments'].iteritems():
    #    c.updateAttachment(k, v['url'])

    return c

class LedgerDatabase(TouchformsStorageUtility):
    def __init__(self, host, domain, auth, additional_filters, preload):
        super(LedgerDatabase, self).__init__(host, domain, auth, additional_filters, preload)

    def get_object_id(self, ledger):
        return ledger.getEntiyId()

    def fetch_object(self, entity_id):
        return query_ledger_for_case(self.query_func, entity_id)

    def load_object_ids(self):
        case_ids = query_case_ids(self.query_func, criteria=self.additional_filters)
        self.ids = dict(enumerate(case_ids))

    def getIDsForValue(self, field_name, value):
        logger.debug('ledger lookup %s %s' % (field_name, value))
        if (field_name, value) not in self.cached_lookups:
            if field_name == 'entity-id':
                ledgers = [self.read_object(value)]
            else:
                raise NotImplementedError("Only entity-id lookup is currently supported!")

            self.cached_lookups[(field_name, value)] = ledgers

        else:
            ledgers = self.cached_lookups[(field_name, value)]

        id_map = dict((v, k) for k, v in self.ids.iteritems())
        return to_vect(id_map[l.getEntiyId()] for l in ledgers)


class CCInstances(InstanceInitializationFactory):

    def __init__(self, sessionvars, api_auth, form_context=None):
        self.vars = sessionvars
        print "SelfVars: ", self.vars
        self.auth = api_auth
        self.fixtures = {}
        self.form_context = form_context or {}

    def generateRoot(self, instance):
        ref = instance.getReference()

        def from_bundle(inst):
            root = inst.getRoot()
            root.setParent(instance.getBase())
            return root
        if 'casedb' in ref:
            casedb = CaseInstanceTreeElement(
                instance.getBase(),
                SQLiteCaseDatabase(
                    self.vars.get('host'),
                    self.vars['domain'],
                    self.auth,
                    self.vars.get("additional_filters", {}),
                    self.vars.get("preload_cases", False),
                    self.form_context,
                    self.vars['user_id'],
                ),
                False
            )
            print "casedb: ", casedb
            return casedb
        elif 'fixture' in ref:
            fixture_id = ref.split('/')[-1]
            user_id = self.vars['user_id']
            ret = self._get_fixture(user_id, fixture_id)
            # Unclear why this is necessary but it is
            ret.setParent(instance.getBase())
            return ret
        elif 'ledgerdb' in ref:
            return LedgerInstanceTreeElement(
                instance.getBase(),
                LedgerDatabase(
                    self.vars.get('host'), self.vars['domain'],
                    self.auth, self.vars.get("additional_filters", {}),
                    self.vars.get("preload_cases", False),
                )
            )

        elif 'session' in ref:
            print "SEssion in ref"
            meta_keys = ['device_id', 'app_version', 'username', 'user_id']
            exclude_keys = ['additional_filters', 'user_data']
            print "Getting session"
            sess = CommCareSession(None) # will not passing a CCPlatform cause problems later?
            for k, v in self.vars.iteritems():
                if k not in meta_keys and k not in exclude_keys:
                    # com.xhaus.jyson.JysonCodec returns data as byte strings
                    # in unknown encoding (possibly ISO-8859-1)
                    sess.setDatum(k, unicode(v, errors='replace'))

            clean_user_data = {}
            for k, v in self.vars.get('user_data', {}).iteritems():
                clean_user_data[k] = unicode(v if v is not None else '', errors='replace')
            print "From Bundle Get Session"
            return from_bundle(sess.getSessionInstance(*([self.vars.get(k, '') for k in meta_keys] + \
                                                         [to_hashtable(clean_user_data)])))

    def _get_fixture(self, user_id, fixture_id):
        query_url = '%(base)s/%(user)s/%(fixture)s' % { "base": settings.FIXTURE_API_URL,
                                                        "user": user_id,
                                                        "fixture": fixture_id }
        q = query_factory(self.vars.get('host'), self.vars['domain'], self.auth, format="raw")
        results = q(query_url)
        parser = KXmlParser()
        parser.setInput(to_input_stream(results), "UTF-8")
        parser.setFeature(KXmlParser.FEATURE_PROCESS_NAMESPACES, True)
        parser.next()
        return TreeElementParser(parser, 0, fixture_id).parse()


def filter_cases(filter_expr, api_auth, session_data=None, form_context=None):
    session_data = session_data or {}
    form_context = form_context or {}
    modified_xpath = "join(',', instance('casedb')/casedb/case%(filters)s/@case_id)" % \
        {"filters": filter_expr}

    # whenever we do a filter case operation we need to load all
    # the cases, so force this unless manually specified
    if 'preload_cases' not in session_data:
        session_data['preload_cases'] = True

    ccInstances = CCInstances(session_data, api_auth, form_context)
    caseInstance = ExternalDataInstance("jr://instance/casedb", "casedb")

    try:
        print "initializing casedb..."
        caseInstance.initialize(ccInstances, "casedb")
    except (HTTPError, URLError), e:
        raise TouchFormsUnauthorized('Unable to connect to HQ: %s' % str(e))

    instances = to_hashtable({"casedb": caseInstance})

    # load any additional instances needed
    for extra_instance_config in session_data.get('extra_instances', []):
        data_instance = ExternalDataInstance(extra_instance_config['src'], extra_instance_config['id'])
        print "initializing data_instance..."
        data_instance.initialize(ccInstances, extra_instance_config['id'])
        instances[extra_instance_config['id']] = data_instance

    try:
        print "case list to string"
        case_list = XPathFuncExpr.toString(
            XPathParseTool.parseXPath(modified_xpath).eval(
                EvaluationContext(None, instances)))
        return {'cases': filter(lambda x: x, case_list.split(","))}
    except (XPathException, XPathSyntaxException), e:
        raise TouchcareInvalidXPath('Error querying cases with xpath %s: %s' % (filter_expr, str(e)))


def load_cases(filter_expr, api_auth, session_data=None, form_context=None):
    session_data = session_data or {}
    form_context = form_context or {}
    modified_xpath = "join(',', instance('casedb')/casedb/case%(filters)s/@case_id)" % \
        {"filters": filter_expr}

    # whenever we do a filter case operation we need to load all
    # the cases, so force this unless manually specified
    if 'preload_cases' not in session_data:
        session_data['preload_cases'] = True

    ccInstances = CCInstances(session_data, api_auth, form_context)
    caseInstance = ExternalDataInstance("jr://instance/casedb", "casedb")
    caseInstance.setName("mycasedb");

    print "caseInstance: ", caseInstance

    try:
        caseInstance.initialize(ccInstances, "casedb")
    except (HTTPError, URLError), e:
        raise TouchFormsUnauthorized('Unable to connect to HQ: %s' % str(e))

    print "caseInstance2: ", caseInstance
    instances = to_hashtable({"casedb": caseInstance})
    print "instances: ", instances

    # load any additional instances needed
    for extra_instance_config in session_data.get('extra_instances', []):
        data_instance = ExternalDataInstance(extra_instance_config['src'], extra_instance_config['id'])
        print "initializing data_instance..."
        data_instance.initialize(ccInstances, extra_instance_config['id'])
        instances[extra_instance_config['id']] = data_instance

    try:
        print "modified_xpath: ", modified_xpath
        print "parsed xpath: ", XPathParseTool.parseXPath(modified_xpath)
        case_list = XPathFuncExpr.toString(
            XPathParseTool.parseXPath(modified_xpath).eval(
                EvaluationContext(None, instances)))
        print "case_list: ", case_list
        print "instances last: ", instances
        return {'cases': filter(lambda x: x, case_list.split(","))}
    except (XPathException, XPathSyntaxException), e:
        raise TouchcareInvalidXPath('Error querying cases with xpath %s' % (str(e)))


class Actions:
    FILTER_CASES = 'touchcare-filter-cases'
