# Copyright (c) 2020 NTT DATA
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import shutil
import zipfile

import fixtures
import mock
from oslo_config import cfg
from tacker.common import exceptions
from tacker.common import utils
from tacker import context
from tacker import objects
from tacker.tests.unit.db import base as db_base
from tacker.tests.unit.vnflcm import fakes
from tacker.tests import uuidsentinel
from tacker.vnflcm import vnflcm_driver


class InfraDriverException(Exception):
    pass


class FakeDriverManager(mock.Mock):
    def __init__(self, fail_method_name=None, vnf_resource_count=1):
        super(FakeDriverManager, self).__init__()
        self.fail_method_name = fail_method_name
        self.vnf_resource_count = vnf_resource_count

    def invoke(self, *args, **kwargs):
        if 'pre_instantiation_vnf' in args:
            vnf_resource_list = [fakes.return_vnf_resource() for index in
                range(self.vnf_resource_count)]
            return {'node_name': vnf_resource_list}
        if 'instantiate_vnf' in args:
            if self.fail_method_name and \
                    self.fail_method_name == 'instantiate_vnf':
                raise InfraDriverException("instantiate_vnf failed")

            instance_id = uuidsentinel.instance_id
            vnfd_dict = kwargs.get('vnfd_dict')
            vnfd_dict['instance_id'] = instance_id
            return instance_id
        if 'create_wait' in args:
            if self.fail_method_name and \
                    self.fail_method_name == 'create_wait':
                raise InfraDriverException("create_wait failed")
        if 'post_vnf_instantiation' in args:
            pass
        if 'delete' in args:
            if self.fail_method_name and \
                    self.fail_method_name == 'delete':
                raise InfraDriverException("delete failed")
        if 'delete_wait' in args:
            if self.fail_method_name and \
                    self.fail_method_name == 'delete_wait':
                raise InfraDriverException("delete_wait failed")
        if 'delete_vnf_instance_resource' in args:
            if self.fail_method_name and \
                    self.fail_method_name == 'delete_vnf_resource':
                raise InfraDriverException("delete_vnf_resource failed")


class FakeVimClient(mock.Mock):
    pass


class TestVnflcmDriver(db_base.SqlTestCase):

    def setUp(self):
        super(TestVnflcmDriver, self).setUp()
        self.addCleanup(mock.patch.stopall)
        self.context = context.get_admin_context()
        self._mock_vim_client()
        self._stub_get_vim()
        self.temp_dir = self.useFixture(fixtures.TempDir()).path

    def _mock_vnf_manager(self, fail_method_name=None, vnf_resource_count=1):
        self._vnf_manager = mock.Mock(wraps=FakeDriverManager(
            fail_method_name=fail_method_name,
            vnf_resource_count=vnf_resource_count))
        self._vnf_manager.__contains__ = mock.Mock(
            return_value=True)
        fake_vnf_manager = mock.Mock()
        fake_vnf_manager.return_value = self._vnf_manager
        self._mock(
            'tacker.common.driver_manager.DriverManager', fake_vnf_manager)

    def _mock_vim_client(self):
        self.vim_client = mock.Mock(wraps=FakeVimClient())
        fake_vim_client = mock.Mock()
        fake_vim_client.return_value = self.vim_client
        self._mock(
            'tacker.vnfm.vim_client.VimClient', fake_vim_client)

    def _stub_get_vim(self):
        vim_obj = {'vim_id': '6261579e-d6f3-49ad-8bc3-a9cb974778ff',
                   'vim_name': 'fake_vim', 'vim_auth':
                       {'auth_url': 'http://localhost/identity', 'password':
                           'test_pw', 'username': 'test_user', 'project_name':
                           'test_project'}, 'vim_type': 'openstack'}
        self.vim_client.get_vim.return_value = vim_obj

    @mock.patch.object(objects.VnfResource, 'create')
    @mock.patch.object(objects.VnfPackageVnfd, 'get_by_id')
    @mock.patch.object(objects.VnfInstance, "save")
    def test_instantiate_vnf(self, mock_vnf_instance_save,
                             mock_vnf_package_vnfd, mock_create):
        vnf_package_vnfd = fakes.return_vnf_package_vnfd()
        vnf_package_id = vnf_package_vnfd.package_uuid
        mock_vnf_package_vnfd.return_value = vnf_package_vnfd
        instantiate_vnf_req_dict = fakes.get_dummy_instantiate_vnf_request()
        instantiate_vnf_req_obj = \
            objects.InstantiateVnfRequest.obj_from_primitive(
                instantiate_vnf_req_dict, self.context)
        vnf_instance_obj = fakes.return_vnf_instance()

        fake_csar = os.path.join(self.temp_dir, vnf_package_id)
        cfg.CONF.set_override('vnf_package_csar_path', self.temp_dir,
                              group='vnf_package')
        base_path = os.path.dirname(os.path.abspath(__file__))
        sample_vnf_package_zip = os.path.join(
            base_path, "../../etc/samples/sample_vnf_package_csar.zip")
        extracted_zip_path = fake_csar
        zipfile.ZipFile(sample_vnf_package_zip, 'r').extractall(
            extracted_zip_path)

        self._mock_vnf_manager()
        driver = vnflcm_driver.VnfLcmDriver()
        driver.instantiate_vnf(self.context, vnf_instance_obj,
                               instantiate_vnf_req_obj)

        self.assertEqual("INSTANTIATED", vnf_instance_obj.instantiation_state)
        self.assertEqual(2, mock_vnf_instance_save.call_count)
        self.assertEqual(4, self._vnf_manager.invoke.call_count)
        shutil.rmtree(fake_csar)

    @mock.patch.object(objects.VnfResource, 'create')
    @mock.patch.object(objects.VnfPackageVnfd, 'get_by_id')
    @mock.patch.object(objects.VnfInstance, "save")
    def test_instantiate_vnf_with_ext_virtual_links(
            self, mock_vnf_instance_save, mock_vnf_package_vnfd, mock_create):
        vnf_package_vnfd = fakes.return_vnf_package_vnfd()
        vnf_package_id = vnf_package_vnfd.package_uuid
        mock_vnf_package_vnfd.return_value = vnf_package_vnfd
        req_body = fakes.get_instantiate_vnf_request_with_ext_virtual_links()
        instantiate_vnf_req_dict = utils.convert_camelcase_to_snakecase(
            req_body)
        instantiate_vnf_req_obj = \
            objects.InstantiateVnfRequest.obj_from_primitive(
                instantiate_vnf_req_dict, self.context)
        vnf_instance_obj = fakes.return_vnf_instance()

        fake_csar = os.path.join(self.temp_dir, vnf_package_id)
        cfg.CONF.set_override('vnf_package_csar_path', self.temp_dir,
                              group='vnf_package')
        base_path = os.path.dirname(os.path.abspath(__file__))
        sample_vnf_package_zip = os.path.join(
            base_path, "../../etc/samples/sample_vnf_package_csar.zip")
        extracted_zip_path = fake_csar
        zipfile.ZipFile(sample_vnf_package_zip, 'r').extractall(
            extracted_zip_path)

        self._mock_vnf_manager()
        driver = vnflcm_driver.VnfLcmDriver()
        driver.instantiate_vnf(self.context, vnf_instance_obj,
                               instantiate_vnf_req_obj)

        self.assertEqual("INSTANTIATED", vnf_instance_obj.instantiation_state)
        self.assertEqual(2, mock_vnf_instance_save.call_count)
        self.assertEqual(4, self._vnf_manager.invoke.call_count)
        shutil.rmtree(fake_csar)

    @mock.patch.object(objects.VnfResource, 'create')
    @mock.patch.object(objects.VnfPackageVnfd, 'get_by_id')
    @mock.patch.object(objects.VnfInstance, "save")
    def test_instantiate_vnf_vim_connection_info(
            self, mock_vnf_instance_save, mock_vnf_package_vnfd, mock_create):
        vnf_package_vnfd = fakes.return_vnf_package_vnfd()
        vnf_package_id = vnf_package_vnfd.package_uuid
        mock_vnf_package_vnfd.return_value = vnf_package_vnfd
        vim_connection_info = fakes.get_dummy_vim_connection_info()
        instantiate_vnf_req_dict = \
            fakes.get_dummy_instantiate_vnf_request(**vim_connection_info)
        instantiate_vnf_req_obj = \
            objects.InstantiateVnfRequest.obj_from_primitive(
                instantiate_vnf_req_dict, self.context)
        vnf_instance_obj = fakes.return_vnf_instance()

        fake_csar = os.path.join(self.temp_dir, vnf_package_id)
        cfg.CONF.set_override('vnf_package_csar_path', self.temp_dir,
                              group='vnf_package')
        base_path = os.path.dirname(os.path.abspath(__file__))
        sample_vnf_package_zip = os.path.join(
            base_path, "../../etc/samples/sample_vnf_package_csar.zip")
        extracted_zip_path = fake_csar
        zipfile.ZipFile(sample_vnf_package_zip, 'r').extractall(
            extracted_zip_path)

        self._mock_vnf_manager()
        driver = vnflcm_driver.VnfLcmDriver()
        driver.instantiate_vnf(self.context, vnf_instance_obj,
                               instantiate_vnf_req_obj)

        self.assertEqual("INSTANTIATED", vnf_instance_obj.instantiation_state)
        self.assertEqual(2, mock_vnf_instance_save.call_count)
        self.assertEqual(4, self._vnf_manager.invoke.call_count)
        shutil.rmtree(fake_csar)

    @mock.patch.object(objects.VnfResource, 'create')
    @mock.patch.object(objects.VnfPackageVnfd, 'get_by_id')
    @mock.patch.object(objects.VnfInstance, "save")
    def test_instantiate_vnf_infra_fails_to_instantiate(
            self, mock_vnf_instance_save, mock_vnf_package_vnfd, mock_create):
        vnf_package_vnfd = fakes.return_vnf_package_vnfd()
        vnf_package_id = vnf_package_vnfd.package_uuid
        mock_vnf_package_vnfd.return_value = vnf_package_vnfd
        vim_connection_info = fakes.get_dummy_vim_connection_info()
        instantiate_vnf_req_dict = \
            fakes.get_dummy_instantiate_vnf_request(**vim_connection_info)
        instantiate_vnf_req_obj = \
            objects.InstantiateVnfRequest.obj_from_primitive(
                instantiate_vnf_req_dict, self.context)
        vnf_instance_obj = fakes.return_vnf_instance()

        fake_csar = os.path.join(self.temp_dir, vnf_package_id)
        cfg.CONF.set_override('vnf_package_csar_path', self.temp_dir,
                              group='vnf_package')
        base_path = os.path.dirname(os.path.abspath(__file__))
        sample_vnf_package_zip = os.path.join(
            base_path, "../../etc/samples/sample_vnf_package_csar.zip")
        extracted_zip_path = fake_csar
        zipfile.ZipFile(sample_vnf_package_zip, 'r').extractall(
            extracted_zip_path)

        self._mock_vnf_manager(fail_method_name="instantiate_vnf")
        driver = vnflcm_driver.VnfLcmDriver()
        error = self.assertRaises(exceptions.VnfInstantiationFailed,
            driver.instantiate_vnf, self.context, vnf_instance_obj,
            instantiate_vnf_req_obj)
        expected_error = ("Vnf instantiation failed for vnf %s, error: "
                          "instantiate_vnf failed")

        self.assertEqual(expected_error % vnf_instance_obj.id, str(error))
        self.assertEqual("NOT_INSTANTIATED",
            vnf_instance_obj.instantiation_state)
        self.assertEqual(1, mock_vnf_instance_save.call_count)
        self.assertEqual(2, self._vnf_manager.invoke.call_count)

        shutil.rmtree(fake_csar)

    @mock.patch.object(objects.VnfResource, 'create')
    @mock.patch.object(objects.VnfPackageVnfd, 'get_by_id')
    @mock.patch.object(objects.VnfInstance, "save")
    def test_instantiate_vnf_infra_fails_to_wait_after_instantiate(
            self, mock_vnf_instance_save, mock_vnf_package_vnfd, mock_create):
        vnf_package_vnfd = fakes.return_vnf_package_vnfd()
        vnf_package_id = vnf_package_vnfd.package_uuid
        mock_vnf_package_vnfd.return_value = vnf_package_vnfd
        vim_connection_info = fakes.get_dummy_vim_connection_info()
        instantiate_vnf_req_dict = \
            fakes.get_dummy_instantiate_vnf_request(**vim_connection_info)
        instantiate_vnf_req_obj = \
            objects.InstantiateVnfRequest.obj_from_primitive(
                instantiate_vnf_req_dict, self.context)
        vnf_instance_obj = fakes.return_vnf_instance()

        fake_csar = os.path.join(self.temp_dir, vnf_package_id)
        cfg.CONF.set_override('vnf_package_csar_path', self.temp_dir,
                              group='vnf_package')
        base_path = os.path.dirname(os.path.abspath(__file__))
        sample_vnf_package_zip = os.path.join(
            base_path, "../../etc/samples/sample_vnf_package_csar.zip")
        extracted_zip_path = fake_csar
        zipfile.ZipFile(sample_vnf_package_zip, 'r').extractall(
            extracted_zip_path)

        self._mock_vnf_manager(fail_method_name='create_wait')
        driver = vnflcm_driver.VnfLcmDriver()
        error = self.assertRaises(exceptions.VnfInstantiationWaitFailed,
            driver.instantiate_vnf, self.context, vnf_instance_obj,
            instantiate_vnf_req_obj)
        expected_error = ("Vnf instantiation wait failed for vnf %s, error: "
                          "create_wait failed")

        self.assertEqual(expected_error % vnf_instance_obj.id, str(error))
        self.assertEqual("NOT_INSTANTIATED",
            vnf_instance_obj.instantiation_state)
        self.assertEqual(1, mock_vnf_instance_save.call_count)
        self.assertEqual(3, self._vnf_manager.invoke.call_count)

        shutil.rmtree(fake_csar)

    @mock.patch.object(objects.VnfResource, 'create')
    @mock.patch.object(objects.VnfPackageVnfd, 'get_by_id')
    @mock.patch.object(objects.VnfInstance, "save")
    def test_instantiate_vnf_with_short_notation(self, mock_vnf_instance_save,
                             mock_vnf_package_vnfd, mock_create):
        vnf_package_vnfd = fakes.return_vnf_package_vnfd()
        vnf_package_id = vnf_package_vnfd.package_uuid
        mock_vnf_package_vnfd.return_value = vnf_package_vnfd
        instantiate_vnf_req_dict = fakes.get_dummy_instantiate_vnf_request()
        instantiate_vnf_req_obj = \
            objects.InstantiateVnfRequest.obj_from_primitive(
                instantiate_vnf_req_dict, self.context)
        vnf_instance_obj = fakes.return_vnf_instance()

        fake_csar = os.path.join(self.temp_dir, vnf_package_id)
        cfg.CONF.set_override('vnf_package_csar_path', self.temp_dir,
                              group='vnf_package')
        base_path = os.path.dirname(os.path.abspath(__file__))
        sample_vnf_package_zip = os.path.join(
            base_path, "../../etc/samples/"
                       "sample_vnf_package_csar_with_short_notation.zip")
        extracted_zip_path = fake_csar
        zipfile.ZipFile(sample_vnf_package_zip, 'r').extractall(
            extracted_zip_path)
        self._mock_vnf_manager(vnf_resource_count=2)
        driver = vnflcm_driver.VnfLcmDriver()
        driver.instantiate_vnf(self.context, vnf_instance_obj,
                               instantiate_vnf_req_obj)
        self.assertEqual(2, mock_create.call_count)
        self.assertEqual("INSTANTIATED", vnf_instance_obj.instantiation_state)
        shutil.rmtree(fake_csar)