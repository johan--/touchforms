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

class DummyServer(xformserver.XFormHTTPGateway):

    def __init__(self):
        pass

class SQLiteTest(unittest.TestCase):

    def setUp(self):
        with open(os.path.join(CUR_DIR, 'test_files/xforms/xform_simple_cases.xml'), 'r') as f:
            self.xform = f.read()
        with open(os.path.join(CUR_DIR, 'test_files/restore.json'), 'r') as f:
            self.restore_payload = f.read()

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
        filter_expr = "[case_name = 'Captainamerica']"

        def json_restore(derp, criteria):
            return self.restore_payload

        touchcare.query_cases = json_restore
        try:
            resp = touchcare.load_cases(
                {},
                self.session_data,
                None,
            )
            print "Resp: ", resp
            self.assertEqual(len(resp['cases']), 1)
        except Throwable, e:
            print "EE, ", e
            e.printStackTrace()



if __name__ == '__main__':
    unittest.main()
