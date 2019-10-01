from __future__ import absolute_import, division, print_function
from os.path import abspath, exists, split, splitext
import ibeis
from ibeis.control import controller_inject
from ibeis.web.apis_engine import ensure_uuid_list
import utool as ut
import requests


#TODO: change this to none and genericize ibeis_plugin_finfindr_ensure_backend
BACKEND_URL = 'localhost:8004'

# just some testing stuff
annot_uuid = 'e6b76954-25d1-4258-9489-7f13a74bd0f8'


(print, rrr, profile) = ut.inject2(__name__)

_, register_ibs_method = controller_inject.make_ibs_register_decorator(__name__)
register_api = controller_inject.get_ibeis_flask_api(__name__)
register_preproc_annot = controller_inject.register_preprocs['annot']

#TODO: this
# def _ibeis_plugin_finfindr_check_container(url):
#     return True


# docker_control.docker_register_config(None, 'finfindr', 'haimeh/finfindr:0.1.7', run_args={'_internal_port': 8004, '_external_suggested_port': 8004}, container_check_func=_ibeis_plugin_finfindr_check_container)


def ibeis_plugin_finfindr_identify(ibs, annot_uuid, dannot_uuids,  use_depc=True, config={}, **kwargs):
    return None


def ibeis_plugin_finfindr_multidentify(ibs, annot_uuids, dannot_uuids,  use_depc=True, config={}, **kwargs):

    url = ibs.ibeis_plugin_finfindr_ensure_backend(**kwargs)
    url = 'http://%s/ocpu/library/finFindR/R/distanceToRefParallel/json' % (url)

    query_hash_data = ibeis_plugin_finfindr_hash(annot_uuid, use_depc)
    reference_hash_data = ibeis_plugin_finfindr_hash


#TODO: test this when the BACKEND_URL init above is None (as opposed ot the literal val)
def ibeis_plugin_finfindr_ensure_backend(ibs, container_name='finfindr'):
    return 'localhost:8004'
    # # below code doesn't work bc of ibeis-scope issue
    # global BACKEND_URL
    # if BACKEND_URL is None:
    #     BACKEND_URLS = ibs.docker_ensure(container_name)
    #     if len(BACKEND_URLS) == 0:
    #         raise RuntimeError('Could not ensure container')
    #     elif len(BACKEND_URLS) == 1:
    #         BACKEND_URL = BACKEND_URLS[0]
    #     else:
    #         BACKEND_URL = BACKEND_URLS[0]
    #         args = (BACKEND_URLS, BACKEND_URL, )
    #         print('[WARNING] Multiple BACKEND_URLS:\n\tFound: %r\n\tUsing: %r' % args)
    # return BACKEND_URL


#curl -v http://localhost:8004/ocpu/library/finFindR/R/hashFromImage/json -F "imageobj=@C:/Users/jathompson/Documents/dolphinTestingdb/jensImgs/test2.jpg"
def ibeis_plugin_finfindr_hash(ibs, annot_uuid, use_depc=False, **kwargs):

    url = ibeis_plugin_finfindr_ensure_backend(ibs, **kwargs)
    url = 'http://%s/ocpu/library/finFindR/R/hashFromImage/json' % (url)

    fpath = finfindr_annot_chip_fpath(ibs, annot_uuid)
    print('Getting finfindr hash from %s' % url)
    # finfindR standard of prepending the @ on fpath
    fpath = '@' + fpath

    data = {
        'imageobj': fpath
    }
    response = requests.post(url, json=data, timeout=120)

    return response


# TODO: move this into the ibeis package. Literally copy-pasted from deepsense right now
def aid_list_from_annot_uuid_list(ibs, annot_uuid_list):
    ibs.web_check_uuids(qannot_uuid_list=annot_uuid_list)
    # Ensure annotations
    annot_uuid_list = ensure_uuid_list(annot_uuid_list)
    aid_list = ibs.get_annot_aids_from_uuid(annot_uuid_list)
    return aid_list


def aid_from_annot_uuid(ibs, annot_uuid):
    return aid_list_from_annot_uuid_list(ibs, [annot_uuid])[0]


#TODO: does this work and is this the desired config for finfindr
def finfindr_annot_chip_fpath(ibs, annot_uuid, **kwargs):
    aid = aid_from_annot_uuid(ibs, annot_uuid)
    return finfindr_annot_chip_fpath_from_aid(ibs, aid, **kwargs)


def finfindr_annot_chip_fpath_from_aid(ibs, aid, **kwargs):
    config = {
        'ext': '.jpg',
    }
    fpath = ibs.get_annot_chip_fpath(aid, ensure=True, config2_=config)
    return fpath


def _ibeis_plugin_finfindr_init_testdb(ibs):
    image_path = abspath('/home/wildme/code/ibeis-finfindr-module/example-images')
    assert exists(image_path)
    gid_list = ibs.import_folder(image_path, ensure_loadable=False, ensure_exif=False)
    uri_list = ibs.get_image_uris_original(gid_list)
    fname_list = [split(uri)[1] for uri in uri_list]
    annot_name_list = [splitext(fname)[0] for fname in fname_list]
    aid_list = ibs.use_images_as_annotations(gid_list)
    ibs.set_annot_names(aid_list, annot_name_list)
    return gid_list, aid_list
