# Copyright 2010 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""
Tests of the new image services, both as a service layer,
and as a WSGI layer
"""

import copy

from lxml import etree
import mock
import six.moves.urllib.parse as urlparse
import webob

from nova.api.openstack.compute import images
from nova.api.openstack.compute.plugins.v3 import images as images_v21
from nova.api.openstack.compute.views import images as images_view
from nova.api.openstack import xmlutil
from nova import exception
from nova.image import glance
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import image_fixtures
from nova.tests import matchers

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"
NOW_API_FORMAT = "2010-10-11T10:30:22Z"
IMAGE_FIXTURES = image_fixtures.get_image_fixtures()


class ImagesControllerTestV21(test.NoDBTestCase):
    """Test of the OpenStack API /images application controller w/Glance.
    """
    image_controller_class = images_v21.ImagesController
    url_base = '/v3'
    bookmark_base = ''
    http_request = fakes.HTTPRequestV3

    def setUp(self):
        """Run before each test."""
        super(ImagesControllerTestV21, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fakes.stub_out_compute_api_snapshot(self.stubs)
        fakes.stub_out_compute_api_backup(self.stubs)

        self.controller = self.image_controller_class()
        self.url_prefix = "http://localhost%s/images" % self.url_base
        self.bookmark_prefix = "http://localhost%s/images" % self.bookmark_base
        self.uuid = 'fa95aaf5-ab3b-4cd8-88c0-2be7dd051aaf'
        self.server_uuid = "aa640691-d1a7-4a67-9d3c-d35ee6b3cc74"
        self.server_href = (
            "http://localhost%s/servers/%s" % (self.url_base,
                                               self.server_uuid))
        self.server_bookmark = (
             "http://localhost%s/servers/%s" % (self.bookmark_base,
                                                self.server_uuid))
        self.alternate = "%s/fake/images/%s"

        self.expected_image_123 = {
            "image": {'id': '123',
                      'name': 'public image',
                      'metadata': {'key1': 'value1'},
                      'updated': NOW_API_FORMAT,
                      'created': NOW_API_FORMAT,
                      'status': 'ACTIVE',
                      'minDisk': 10,
                      'progress': 100,
                      'minRam': 128,
                      "links": [{
                                    "rel": "self",
                                    "href": "%s/123" % self.url_prefix
                                },
                                {
                                    "rel": "bookmark",
                                    "href":
                                        "%s/123" % self.bookmark_prefix
                                },
                                {
                                    "rel": "alternate",
                                    "type": "application/vnd.openstack.image",
                                    "href": self.alternate %
                                            (glance.generate_glance_url(),
                                             123),
                                }],
            },
        }

        self.expected_image_124 = {
            "image": {'id': '124',
                      'name': 'queued snapshot',
                      'metadata': {
                          u'instance_uuid': self.server_uuid,
                          u'user_id': u'fake',
                      },
                      'updated': NOW_API_FORMAT,
                      'created': NOW_API_FORMAT,
                      'status': 'SAVING',
                      'progress': 25,
                      'minDisk': 0,
                      'minRam': 0,
                      'server': {
                          'id': self.server_uuid,
                          "links": [{
                                        "rel": "self",
                                        "href": self.server_href,
                                    },
                                    {
                                        "rel": "bookmark",
                                        "href": self.server_bookmark,
                                    }],
                      },
                      "links": [{
                                    "rel": "self",
                                    "href": "%s/124" % self.url_prefix
                                },
                                {
                                    "rel": "bookmark",
                                    "href":
                                        "%s/124" % self.bookmark_prefix
                                },
                                {
                                    "rel": "alternate",
                                    "type":
                                        "application/vnd.openstack.image",
                                    "href": self.alternate %
                                            (glance.generate_glance_url(),
                                             124),
                                }],
            },
        }

    @mock.patch('nova.image.api.API.get', return_value=IMAGE_FIXTURES[0])
    def test_get_image(self, get_mocked):
        request = self.http_request.blank(self.url_base + 'images/123')
        actual_image = self.controller.show(request, '123')
        self.assertThat(actual_image,
                        matchers.DictMatches(self.expected_image_123))
        get_mocked.assert_called_once_with(mock.ANY, '123')

    @mock.patch('nova.image.api.API.get', return_value=IMAGE_FIXTURES[1])
    def test_get_image_with_custom_prefix(self, _get_mocked):
        self.flags(osapi_compute_link_prefix='https://zoo.com:42',
                   osapi_glance_link_prefix='http://circus.com:34')
        fake_req = self.http_request.blank(self.url_base + 'images/124')
        actual_image = self.controller.show(fake_req, '124')

        expected_image = self.expected_image_124
        expected_image["image"]["links"][0]["href"] = (
            "https://zoo.com:42%s/images/124" % self.url_base)
        expected_image["image"]["links"][1]["href"] = (
            "https://zoo.com:42%s/images/124" % self.bookmark_base)
        expected_image["image"]["links"][2]["href"] = (
            "http://circus.com:34/fake/images/124")
        expected_image["image"]["server"]["links"][0]["href"] = (
            "https://zoo.com:42%s/servers/%s" % (self.url_base,
                                                 self.server_uuid))
        expected_image["image"]["server"]["links"][1]["href"] = (
            "https://zoo.com:42%s/servers/%s" % (self.bookmark_base,
                                                 self.server_uuid))

        self.assertThat(actual_image, matchers.DictMatches(expected_image))

    @mock.patch('nova.image.api.API.get', side_effect=exception.NotFound)
    def test_get_image_404(self, _get_mocked):
        fake_req = self.http_request.blank(self.url_base + 'images/unknown')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, fake_req, 'unknown')

    @mock.patch('nova.image.api.API.get_all', return_value=IMAGE_FIXTURES)
    def test_get_image_details(self, get_all_mocked):
        request = self.http_request.blank(self.url_base + 'images/detail')
        response = self.controller.detail(request)

        get_all_mocked.assert_called_once_with(mock.ANY, filters={})
        response_list = response["images"]

        image_125 = copy.deepcopy(self.expected_image_124["image"])
        image_125['id'] = '125'
        image_125['name'] = 'saving snapshot'
        image_125['progress'] = 50
        image_125["links"][0]["href"] = "%s/125" % self.url_prefix
        image_125["links"][1]["href"] = "%s/125" % self.bookmark_prefix
        image_125["links"][2]["href"] = (
            "%s/fake/images/125" % glance.generate_glance_url())

        image_126 = copy.deepcopy(self.expected_image_124["image"])
        image_126['id'] = '126'
        image_126['name'] = 'active snapshot'
        image_126['status'] = 'ACTIVE'
        image_126['progress'] = 100
        image_126["links"][0]["href"] = "%s/126" % self.url_prefix
        image_126["links"][1]["href"] = "%s/126" % self.bookmark_prefix
        image_126["links"][2]["href"] = (
            "%s/fake/images/126" % glance.generate_glance_url())

        image_127 = copy.deepcopy(self.expected_image_124["image"])
        image_127['id'] = '127'
        image_127['name'] = 'killed snapshot'
        image_127['status'] = 'ERROR'
        image_127['progress'] = 0
        image_127["links"][0]["href"] = "%s/127" % self.url_prefix
        image_127["links"][1]["href"] = "%s/127" % self.bookmark_prefix
        image_127["links"][2]["href"] = (
            "%s/fake/images/127" % glance.generate_glance_url())

        image_128 = copy.deepcopy(self.expected_image_124["image"])
        image_128['id'] = '128'
        image_128['name'] = 'deleted snapshot'
        image_128['status'] = 'DELETED'
        image_128['progress'] = 0
        image_128["links"][0]["href"] = "%s/128" % self.url_prefix
        image_128["links"][1]["href"] = "%s/128" % self.bookmark_prefix
        image_128["links"][2]["href"] = (
            "%s/fake/images/128" % glance.generate_glance_url())

        image_129 = copy.deepcopy(self.expected_image_124["image"])
        image_129['id'] = '129'
        image_129['name'] = 'pending_delete snapshot'
        image_129['status'] = 'DELETED'
        image_129['progress'] = 0
        image_129["links"][0]["href"] = "%s/129" % self.url_prefix
        image_129["links"][1]["href"] = "%s/129" % self.bookmark_prefix
        image_129["links"][2]["href"] = (
            "%s/fake/images/129" % glance.generate_glance_url())

        image_130 = copy.deepcopy(self.expected_image_123["image"])
        image_130['id'] = '130'
        image_130['name'] = None
        image_130['metadata'] = {}
        image_130['minDisk'] = 0
        image_130['minRam'] = 0
        image_130["links"][0]["href"] = "%s/130" % self.url_prefix
        image_130["links"][1]["href"] = "%s/130" % self.bookmark_prefix
        image_130["links"][2]["href"] = (
            "%s/fake/images/130" % glance.generate_glance_url())

        image_131 = copy.deepcopy(self.expected_image_123["image"])
        image_131['id'] = '131'
        image_131['name'] = None
        image_131['metadata'] = {}
        image_131['minDisk'] = 0
        image_131['minRam'] = 0
        image_131["links"][0]["href"] = "%s/131" % self.url_prefix
        image_131["links"][1]["href"] = "%s/131" % self.bookmark_prefix
        image_131["links"][2]["href"] = (
            "%s/fake/images/131" % glance.generate_glance_url())

        expected = [self.expected_image_123["image"],
                    self.expected_image_124["image"],
                    image_125, image_126, image_127,
                    image_128, image_129, image_130,
                    image_131]

        self.assertThat(expected, matchers.DictListMatches(response_list))

    @mock.patch('nova.image.api.API.get_all')
    def test_get_image_details_with_limit(self, get_all_mocked):
        request = self.http_request.blank(self.url_base +
                                          'images/detail?limit=2')
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, limit=2, filters={})

    @mock.patch('nova.image.api.API.get_all')
    def test_get_image_details_with_limit_and_page_size(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'images/detail?limit=2&page_size=1')
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, limit=2, filters={},
                                               page_size=1)

    @mock.patch('nova.image.api.API.get_all')
    def _detail_request(self, filters, request, get_all_mocked):
        self.controller.detail(request)
        get_all_mocked.assert_called_once_with(mock.ANY, filters=filters)

    def test_image_detail_filter_with_name(self):
        filters = {'name': 'testname'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?name=testname')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_status(self):
        filters = {'status': 'active'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?status=ACTIVE')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_property(self):
        filters = {'property-test': '3'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?property-test=3')
        self._detail_request(filters, request)

    def test_image_detail_filter_server_href(self):
        filters = {'property-instance_uuid': self.uuid}
        request = self.http_request.blank(
            self.url_base + 'images/detail?server=' + self.uuid)
        self._detail_request(filters, request)

    def test_image_detail_filter_server_uuid(self):
        filters = {'property-instance_uuid': self.uuid}
        request = self.http_request.blank(
            self.url_base + 'images/detail?server=' + self.uuid)
        self._detail_request(filters, request)

    def test_image_detail_filter_changes_since(self):
        filters = {'changes-since': '2011-01-24T17:08Z'}
        request = self.http_request.blank(self.url_base + 'images/detail'
                                          '?changes-since=2011-01-24T17:08Z')
        self._detail_request(filters, request)

    def test_image_detail_filter_with_type(self):
        filters = {'property-image_type': 'BASE'}
        request = self.http_request.blank(
            self.url_base + 'images/detail?type=BASE')
        self._detail_request(filters, request)

    def test_image_detail_filter_not_supported(self):
        filters = {'status': 'active'}
        request = self.http_request.blank(
            self.url_base + 'images/detail?status='
            'ACTIVE&UNSUPPORTEDFILTER=testname')
        self._detail_request(filters, request)

    def test_image_detail_no_filters(self):
        filters = {}
        request = self.http_request.blank(self.url_base + 'images/detail')
        self._detail_request(filters, request)

    @mock.patch('nova.image.api.API.get_all', side_effect=exception.Invalid)
    def test_image_detail_invalid_marker(self, _get_all_mocked):
        request = self.http_request.blank(self.url_base + '?marker=invalid')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.detail,
                          request)

    def test_generate_alternate_link(self):
        view = images_view.ViewBuilder()
        request = self.http_request.blank(self.url_base + 'images/1')
        generated_url = view._get_alternate_link(request, 1)
        actual_url = "%s/fake/images/1" % glance.generate_glance_url()
        self.assertEqual(generated_url, actual_url)

    def _check_response(self, controller_method, response, expected_code):
        self.assertEqual(expected_code, controller_method.wsgi_code)

    @mock.patch('nova.image.api.API.delete')
    def test_delete_image(self, delete_mocked):
        request = self.http_request.blank(self.url_base + 'images/124')
        request.method = 'DELETE'
        response = self.controller.delete(request, '124')
        self._check_response(self.controller.delete, response, 204)
        delete_mocked.assert_called_once_with(mock.ANY, '124')

    @mock.patch('nova.image.api.API.delete',
                side_effect=exception.ImageNotAuthorized(image_id='123'))
    def test_delete_deleted_image(self, _delete_mocked):
        # If you try to delete a deleted image, you get back 403 Forbidden.
        request = self.http_request.blank(self.url_base + 'images/123')
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.delete,
                          request, '123')

    @mock.patch('nova.image.api.API.delete',
                side_effect=exception.ImageNotFound(image_id='123'))
    def test_delete_image_not_found(self, _delete_mocked):
        request = self.http_request.blank(self.url_base + 'images/300')
        request.method = 'DELETE'
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, request, '300')

    @mock.patch('nova.image.api.API.get_all', return_value=[IMAGE_FIXTURES[0]])
    def test_get_image_next_link(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'imagesl?limit=1')
        response = self.controller.index(request)
        response_links = response['images_links']
        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual(self.url_base + '/images', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': [IMAGE_FIXTURES[0]['id']]},
                        matchers.DictMatches(params))

    @mock.patch('nova.image.api.API.get_all', return_value=[IMAGE_FIXTURES[0]])
    def test_get_image_details_next_link(self, get_all_mocked):
        request = self.http_request.blank(
            self.url_base + 'images/detail?limit=1')
        response = self.controller.detail(request)
        response_links = response['images_links']
        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual(self.url_base + '/images/detail', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': [IMAGE_FIXTURES[0]['id']]},
                        matchers.DictMatches(params))


class ImagesControllerTestV2(ImagesControllerTestV21):
    image_controller_class = images.Controller
    url_base = '/v2/fake'
    bookmark_base = '/fake'
    http_request = fakes.HTTPRequest

    def _check_response(self, controller_method, response, expected_code):
        self.assertEqual(expected_code, response.status_int)


class ImageXMLSerializationTest(test.NoDBTestCase):

    TIMESTAMP = "2010-10-11T10:30:22Z"
    SERVER_UUID = 'aa640691-d1a7-4a67-9d3c-d35ee6b3cc74'
    SERVER_HREF = 'http://localhost/v2/fake/servers/' + SERVER_UUID
    SERVER_BOOKMARK = 'http://localhost/fake/servers/' + SERVER_UUID
    IMAGE_HREF = 'http://localhost/v2/fake/images/%s'
    IMAGE_NEXT = 'http://localhost/v2/fake/images?limit=%s&marker=%s'
    IMAGE_BOOKMARK = 'http://localhost/fake/images/%s'

    def test_xml_declaration(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'minRam': 10,
                'minDisk': 100,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status', 'progress']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_zero_metadata(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {},
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        meta_nodes = root.findall('{0}meta'.format(ATOMNS))
        self.assertEqual(len(meta_nodes), 0)

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_image_no_metadata_key(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        meta_nodes = root.findall('{0}meta'.format(ATOMNS))
        self.assertEqual(len(meta_nodes), 0)

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_no_server(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertIsNone(server_root)

    def test_show_with_min_ram(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'minRam': 256,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status', 'progress',
                    'minRam']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_with_min_disk(self):
        serializer = images.ImageTemplate()

        fixture = {
            'image': {
                'id': 1,
                'name': 'Image1',
                'created': self.TIMESTAMP,
                'updated': self.TIMESTAMP,
                'status': 'ACTIVE',
                'progress': 80,
                'minDisk': 5,
                'server': {
                    'id': self.SERVER_UUID,
                    'links': [
                        {
                            'href': self.SERVER_HREF,
                            'rel': 'self',
                        },
                        {
                            'href': self.SERVER_BOOKMARK,
                            'rel': 'bookmark',
                        },
                    ],
                },
                'metadata': {
                    'key1': 'value1',
                },
                'links': [
                    {
                        'href': self.IMAGE_HREF % 1,
                        'rel': 'self',
                    },
                    {
                        'href': self.IMAGE_BOOKMARK % 1,
                        'rel': 'bookmark',
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'image')
        image_dict = fixture['image']

        for key in ['name', 'id', 'updated', 'created', 'status', 'progress',
                    'minDisk']:
            self.assertEqual(root.get(key), str(image_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

        metadata_root = root.find('{0}metadata'.format(NS))
        metadata_elems = metadata_root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = image_dict['metadata'].items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

        server_root = root.find('{0}server'.format(NS))
        self.assertEqual(server_root.get('id'), image_dict['server']['id'])
        link_nodes = server_root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(image_dict['server']['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_index(self):
        serializer = images.MinimalImagesTemplate()

        fixture = {
            'images': [
                {
                    'id': 1,
                    'name': 'Image1',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 1,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 1,
                            'rel': 'bookmark',
                        },
                    ],
                },
                {
                    'id': 2,
                    'name': 'Image2',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 2,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 2,
                            'rel': 'bookmark',
                        },
                    ],
                },
            ]
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images_index')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 2)
        for i, image_elem in enumerate(image_elems):
            image_dict = fixture['images'][i]

            for key in ['name', 'id']:
                self.assertEqual(image_elem.get(key), str(image_dict[key]))

            link_nodes = image_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(image_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_index_with_links(self):
        serializer = images.MinimalImagesTemplate()

        fixture = {
            'images': [
                {
                    'id': 1,
                    'name': 'Image1',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 1,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 1,
                            'rel': 'bookmark',
                        },
                    ],
                },
                {
                    'id': 2,
                    'name': 'Image2',
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 2,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 2,
                            'rel': 'bookmark',
                        },
                    ],
                },
            ],
            'images_links': [
                {
                    'rel': 'next',
                    'href': self.IMAGE_NEXT % (2, 2),
                }
            ],
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images_index')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 2)
        for i, image_elem in enumerate(image_elems):
            image_dict = fixture['images'][i]

            for key in ['name', 'id']:
                self.assertEqual(image_elem.get(key), str(image_dict[key]))

            link_nodes = image_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(image_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

            # Check images_links
            images_links = root.findall('{0}link'.format(ATOMNS))
            for i, link in enumerate(fixture['images_links']):
                for key, value in link.items():
                    self.assertEqual(images_links[i].get(key), value)

    def test_index_zero_images(self):
        serializer = images.MinimalImagesTemplate()

        fixtures = {
            'images': [],
        }

        output = serializer.serialize(fixtures)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images_index')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 0)

    def test_detail(self):
        serializer = images.ImagesTemplate()

        fixture = {
            'images': [
                {
                    'id': 1,
                    'name': 'Image1',
                    'created': self.TIMESTAMP,
                    'updated': self.TIMESTAMP,
                    'status': 'ACTIVE',
                    'server': {
                        'id': self.SERVER_UUID,
                        'links': [
                            {
                                'href': self.SERVER_HREF,
                                'rel': 'self',
                            },
                            {
                                'href': self.SERVER_BOOKMARK,
                                'rel': 'bookmark',
                            },
                        ],
                    },
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 1,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 1,
                            'rel': 'bookmark',
                        },
                    ],
                },
                {
                    'id': '2',
                    'name': 'Image2',
                    'created': self.TIMESTAMP,
                    'updated': self.TIMESTAMP,
                    'status': 'SAVING',
                    'progress': 80,
                    'metadata': {
                        'key1': 'value1',
                    },
                    'links': [
                        {
                            'href': self.IMAGE_HREF % 2,
                            'rel': 'self',
                        },
                        {
                            'href': self.IMAGE_BOOKMARK % 2,
                            'rel': 'bookmark',
                        },
                    ],
                },
            ]
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'images')
        image_elems = root.findall('{0}image'.format(NS))
        self.assertEqual(len(image_elems), 2)
        for i, image_elem in enumerate(image_elems):
            image_dict = fixture['images'][i]

            for key in ['name', 'id', 'updated', 'created', 'status']:
                self.assertEqual(image_elem.get(key), str(image_dict[key]))

            link_nodes = image_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(image_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)
