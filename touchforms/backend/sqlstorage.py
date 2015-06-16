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
    def __init__(self, host, domain, auth, restore, additional_filters=None, preload=False,
                 form_context=None, user_id=None):
        self.user_id = user_id
        self.database_name = '%s-casedb.db' % user_id
        self.drop_table()
        self.create_table()
        self.restore = restore
        self.restore()

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
        sel_sql = "SELECT * FROM TFCase WHERE case_id = ?"
        sel_params = [id]
        conn = sqlite_get_connection(self.database_name)
        cursor = conn.cursor()
        cursor.execute(sel_sql, sel_params)
        row = cursor.fetchone()
        case = self.case_from_row(row)
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

    def getRecordForValue(self, fieldname, value):
        id = self.getIDsForValue(fieldname, value)[0]
        return self.read(id)

    def iterate(self):
        sel_sql = "SELECT commcare_sql_id FROM TFCase"
        conn = sqlite_get_connection(self.database_name)
        cursor = conn.cursor()
        cursor.execute(sel_sql)
        rows = cursor.fetchall()
        cursor.close()
        conn.commit()
        conn.close()
        return StaticIterator(rows)

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

        print "properties: ", properties.getClass()

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