from __future__ import absolute_import, division, print_function
from os.path import abspath, exists, join, dirname, split
import ibeis
from ibeis.control import controller_inject
from ibeis.constants import ANNOTATION_TABLE
from ibeis.web.apis_engine import ensure_uuid_list
import utool as ut
import dtool as dt
import vtool as vt
 import requests
from PIL import Image, ImageDraw


#TODO: change this to none and genericize ibeis_plugin_finfindr_ensure_backend
BACKEND_URL = 'localhost:8004'
DIM_SIZE = 2000

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


@register_ibs_method
def ibeis_plugin_finfindr_identify(ibs, qaid_list, daid_list,  use_depc=True, config={}, **kwargs):

    q_hash_dict = ibs.finfindr_aid_hash_dict(qaid_list)
    d_hash_dict = ibs.finfindr_aid_hash_dict(daid_list)

    finfindr_arg_dict = {}
    finfindr_arg_dict['queryHashData'] = q_hash_dict
    finfindr_arg_dict['referenceHashData'] = d_hash_dict

    url = ibs.finfindr_ensure_backend(**kwargs)
    url = 'http://%s/ocpu/library/finFindR/R/distanceToRefParallel/json' % (url)

    response = requests.post(url, json=finfindr_arg_dict)
    return response


# this method takes an aid_list and returns the arguments finFindR needs to do matching for those aid[p]
@register_ibs_method
def finfindr_aid_hash_dict(ibs, aid_list):

    annot_hash_data = ibs.depc_annot.get('FinfindrHash', aid_list, 'response')
    aid_hash_dict = {}
    for aid, hash_data in zip(aid_list, annot_hash_data):
        # hash_result comes from finFindR in this format
        aid_hash_dict[aid] = hash_data['hash'][0]
        #TODO: should we throw an exception in cases where there's mult images for one name?

    return aid_hash_dict


#TODO: test this when the BACKEND_URL init above is None (as opposed ot the literal val)
@register_ibs_method
def finfindr_ensure_backend(ibs, container_name='finfindr'):
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
@register_ibs_method
def finfindr_hash_aid(ibs, aid, use_depc=False, **kwargs):

    json_result = ibs.finfindr_hash_from_image_aid(aid, **kwargs)
    return json_result['hash'][0]


@register_ibs_method
def finfindr_hash_from_image_aid(ibs, aid, use_depc=False, **kwargs):

    url = ibs.finfindr_ensure_backend(**kwargs)
    url = 'http://%s/ocpu/library/finFindR/R/hashFromImage/json' % (url)

    fpath = ibs.finfindr_annot_chip_fpath_from_aid(aid)
    print('Getting finfindr hash from %s' % url)

    image_file = open(fpath, 'rb')
    post_file  = {
        'imageobj': image_file
    }

    response = requests.post(url, files=post_file, timeout=120)
    image_file.close()

    # TODO throw error if any code other than 201

    import json
    json_result = json.loads(response.content)

    # VISUALIZATION: I believe json_result.coordinates is the extracted outline of the fin

    return json_result


class FinfindrHashConfig(dt.Config):  # NOQA
    _param_info_list = []


@register_preproc_annot(
    tablename='FinfindrHash', parents=[ANNOTATION_TABLE],
    colnames=['response'], coltypes=[dict],
    configclass=FinfindrHashConfig,
    fname='finfindr',
    chunksize=128)
def finfindr_hash_from_image_aid_depc(depc, aid_list, config):
    # The doctest for ibeis_plugin_deepsense_identify_deepsense_ids also covers this func
    ibs = depc.controller
    for aid in aid_list:
        response = ibs.finfindr_hash_from_image_aid(aid)
        yield (response, )


@register_ibs_method
def finfindr_passport(ibs, aid, output=False, config={}, **kwargs):

    edge_coords = ibs.depc_annot.get('FinfindrHash', [aid], 'response')[0]['coordinates']
    image_path  = ibs.finfindr_annot_chip_fpath_from_aid(aid)
    pil_image   = Image.open(image_path)

    # we now modify pil_image and save it elsewhere when we're done
    draw = ImageDraw.Draw(pil_image)
    # convert edge_coords to the format draw.line is looking for
    edge_coord_tuples = [(coord[0], coord[1]) for coord in edge_coords]
    draw.line(xy=edge_coord_tuples, fill='yellow', width=3)

    if output:
        local_path = dirname(abspath(__file__))
        output_path = abspath(join(local_path, '..', '_output'))
        ut.ensuredir(output_path)
        output_filepath_fmtstr = join(output_path, 'passport-%s.png')
        # TODO: save to UUID not aid
        # output_filepath = output_filepath_fmtstr % (annot_uuid, )
        output_filepath = output_filepath_fmtstr % (aid, )
        print('Writing to %s' % (output_filepath, ))
        pil_image.save(output_filepath)

    return pil_image


# TODO: ask JP if it's kosher to duplicate this func also defined in ibeis-deepsense-module
def pil_image_load(absolute_path):
    pil_img = Image.open(absolute_path)
    return pil_img


def pil_image_write(absolute_path, pil_img):
    pil_img.save(absolute_path)  # error on this line as it tries to save it as .cpkl


class FinfindrPassportConfig(dt.Config):  # NOQA
    _param_info_list = [
        # TODO: is dim_size necessary?
        ut.ParamInfo('dim_size', DIM_SIZE),
        ut.ParamInfo('ext', '.jpg')
    ]


@register_preproc_annot(
    tablename='FinfindrPassport', parents=[ANNOTATION_TABLE],
    colnames=['image'], coltypes=[('extern', pil_image_load, pil_image_write)],
    configclass=FinfindrPassportConfig,
    fname='finfindr',
    chunksize=128)
def finfindr_passport_depc(depc, aid_list, config):
    # The doctest for ibeis_plugin_deepsense_identify_deepsense_ids also covers this func
    ibs = depc.controller
    for aid in aid_list:
        image = ibs.finfindr_passport(aid, config=config)
        yield (image, )


# TODO: move this into the ibeis package. Literally copy-pasted from deepsense right now
@register_ibs_method
def finfindr_aid_list_from_annot_uuid_list(ibs, annot_uuid_list):
    # do we need to do the following check?
    #ibs.web_check_uuids(qannot_uuid_list=annot_uuid_list)
    # Ensure annotations
    annot_uuid_list = ensure_uuid_list(annot_uuid_list)
    aid_list = ibs.get_annot_aids_from_uuid(annot_uuid_list)
    return aid_list


# @register_ibs_method
# def finfindr_aid_from_annot_uuid(ibs, annot_uuid):
#     return ibs.finfindr_aid_list_from_annot_uuid_list([annot_uuid])[0]


#TODO: does this work and is this the desired config for finfindr
@register_ibs_method
def finfindr_annot_chip_fpath(ibs, annot_uuid, **kwargs):
    aid = ibs.finfindr_aid_from_annot_uuid(annot_uuid)
    return ibs.finfindr_annot_chip_fpath_from_aid(aid, **kwargs)


@register_ibs_method
def finfindr_annot_chip_fpath_from_aid(ibs, aid, **kwargs):
    config = {
        'ext': '.jpg',
    }
    fpath = ibs.get_annot_chip_fpath(aid, ensure=True, config2_=config)
    return fpath


@register_ibs_method
def finfindr_aid_from_annot_uuid(ibs, annot_uuid):
    annot_uuid_list = [annot_uuid]
    ibs.web_check_uuids(qannot_uuid_list=annot_uuid_list)
    annot_uuid_list = ensure_uuid_list(annot_uuid_list)
    # Ensure annotations
    aid_list = ibs.get_annot_aids_from_uuid(annot_uuid_list)
    aid = aid_list[0]
    return aid


@register_ibs_method
def finfindr_init_testdb(ibs):
    image_path = abspath('/home/wildme/code/ibeis-finfindr-module/example-images')
    assert exists(image_path)
    gid_list = ibs.import_folder(image_path, ensure_loadable=False, ensure_exif=False)
    uri_list = ibs.get_image_uris_original(gid_list)
    fname_list = [split(uri)[1] for uri in uri_list]
    # annot_name_list not using splitext but split('.') so we can get mult images per indiv.
    annot_name_list = [fname.split('.')[0] for fname in fname_list]
    aid_list = ibs.use_images_as_annotations(gid_list)
    ibs.set_annot_names(aid_list, annot_name_list)
    return gid_list, aid_list


class FinfindrConfig(dt.Config):  # NOQA
    """
    CommandLine:
        python -m ibeis_deepsense._plugin --test-FinfindrConfig

    Example:
        >>> # ENABLE_DOCTEST
        >>> from ibeis_deepsense._plugin import *  # NOQA
        >>> config = FinfindrConfig()
        >>> result = config.get_cfgstr()
        >>> print(result)
        Finfindr(dim_size=2000)
    """
    def get_param_info_list(self):
        return [
            ut.ParamInfo('dim_size', DIM_SIZE),
        ]


class FinfindrRequest(dt.base.VsOneSimilarityRequest):
    _symmetric = False
    _tablename = 'Finfindr'

    @ut.accepts_scalar_input
    def get_fmatch_overlayed_chip(request, aid_list, config=None):
        depc = request.depc
        ibs = depc.controller
        passport_paths = ibs.depc_annot.get('FinfindrPassport', aid_list, 'image', config=config, read_extern=False, ensure=True)
        passports = list(map(vt.imread, passport_paths))
        return passports

    def render_single_result(request, cm, aid, **kwargs):
        # HACK FOR WEB VIEWER
        chips = request.get_fmatch_overlayed_chip([cm.qaid, aid], config=request.config)
        out_img = vt.stack_image_list(chips)
        return out_img

    def postprocess_execute(request, parent_rowids, result_list):
        qaid_list, daid_list = list(zip(*parent_rowids))
        score_list = ut.take_column(result_list, 0)
        depc = request.depc
        config = request.config
        cm_list = list(get_match_results(depc, qaid_list, daid_list,
                                         score_list, config))
        return cm_list

    def execute(request, *args, **kwargs):
        kwargs['use_cache'] = False
        result_list = super(FinfindrRequest, request).execute(*args, **kwargs)
        qaids = kwargs.pop('qaids', None)
        # TODO: is this filtering necessary?
        if qaids is not None:
            result_list = [
                result for result in result_list
                if result.qaid in qaids
            ]
        return result_list


@register_preproc_annot(
    tablename='Finfindr', parents=[ANNOTATION_TABLE, ANNOTATION_TABLE],
    colnames=['score'], coltypes=[float],
    configclass=FinfindrConfig,
    requestclass=FinfindrRequest,
    fname='deepsense',
    rm_extern_on_delete=True,
    chunksize=None)
def ibeis_plugin_finfindr(depc, qaid_list, daid_list, config):
    ibs = depc.controller

    qaids = list(set(qaid_list))
    daids = list(set(daid_list))

    # note that finfindr itself doesn't have this constraint; this is ibeis
    assert len(qaids) == 1

    qaid = qaids[0]
    annot_uuid = ibs.get_annot_uuids(qaid)
    resp_json = ibs.ibeis_plugin_deepsense_identify(annot_uuid, use_depc=True, config=config)
