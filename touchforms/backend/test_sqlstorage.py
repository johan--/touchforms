from __future__ import with_statement
import unittest
import os

from setup import init_classpath
init_classpath()

import touchcare
from xcp import TouchcareInvalidXPath, TouchFormsUnauthorized
import xformserver
CUR_DIR = os.path.dirname(__file__)
from java.lang import Throwable
from sqlstorage import SQLiteCaseDatabase
import com.xhaus.jyson.JysonCodec as json

class DummyServer(xformserver.XFormHTTPGateway):

    def __init__(self):
        pass

class SQLiteTest(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(CUR_DIR, 'test_files/xforms/xform_simple_cases.xml'), 'r') as f:
            self.xform = f.read()
        with open(os.path.join(CUR_DIR, 'test_files/restore1.json'), 'r') as f:
            self.restore_payload = f.read()
        with open(os.path.join(CUR_DIR, 'test_files/restore2.json'), 'r') as f:
            self.restore_payload_2 = f.read()

        self.session_data = {
            'session_name': 'Village Healthe > Simple Form',
            'app_version': '2.0',
            'device_id': 'cloudcare',
            'user_id': '51cd680c0bd1c21bb5e63dab99748248',
            'additional_filters': {'footprint': True},
            'domain': 'aspace',
            'host': 'http://localhost:8000',
            'user_data': {},
            'case_id_new_RegCase_0': '1c2e7c76f0c84eaea5b44bc7d1d3caf0',
            'app_id': '6a48b8838d06febeeabb28c8c9516ab6',
            'username': 'ben'
        }

    def test_load_cases(self):
        self.auth=None
        self.form_context = {}
        self.vars = self.session_data
        sql_storage = SQLiteCaseDatabase(
                    self.vars.get('host'),
                    self.vars['domain'],
                    self.auth,
                    self.vars.get("additional_filters", {}),
                    self.vars.get("preload_cases", False),
                    self.form_context,
                    self.vars['user_id'],
        )
        c = touchcare.case_from_json(json.loads(self.restore_payload))
        c2 = touchcare.case_from_json(json.loads(self.restore_payload_2))

        sql_storage.write(c)
        sql_storage.write(c2)

        ids_for_value = sql_storage.getIDsForValue("case_name", "Test")

        rec = sql_storage.getRecordForValue("case_id", "de9da558-1957-4c26-8ff1-11a7a90f951d")

        ids = sql_storage.iterate(False)
        print "IDs: ", ids

if __name__ == '__main__':
    unittest.main()
