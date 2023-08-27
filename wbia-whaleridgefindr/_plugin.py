# -*- coding: utf-8 -*-
import logging
from os.path import abspath, exists, join, dirname, split
import wbia
from wbia.control import controller_inject, docker_control
from wbia.constants import ANNOTATION_TABLE
from wbia.web.apis_engine import ensure_uuid_list
from wbia import dtool as dt
import numpy as np
import utool as ut
import vtool as vt
import requests
from PIL import Image, ImageDraw


# Section: Global vars
BACKEND_URL = None
DIM_SIZE = 2000


GLOBAL_FEATURE_IN_MEMORY_CACHE = {}


# Section: wbia binds
(print, rrr, profile) = ut.inject2(__name__)
logger = logging.getLogger()
_, register_ibs_method = controller_inject.make_ibs_register_decorator(__name__)
register_api = controller_inject.get_wbia_flask_api(__name__)
register_preproc_annot = controller_inject.register_preprocs['annot']


register_route = controller_inject.get_wbia_flask_route(__name__)


# TODO: abstract this out to a func that takes endpoints as an arg and lives in the docker controller
def _wbia_plugin_whaleridgefindr_check_container(url):
    endpoints = {
        'ocpu/library/finFindR/R/hashFromImage/json': ['POST'],
        'ocpu/library/finFindR/R/distanceToRefParallel/json': ['POST'],
    }
    flag_list = []
    endpoint_list = list(endpoints.keys())
    for endpoint in endpoint_list:
        logger.info('Checking endpoint %r against url %r' % (endpoint, url))
        flag = False
        required_methods = set(endpoints[endpoint])
        supported_methods = None
        url_ = 'http://%s/%s' % (url, endpoint)

        try:
            # http options returns the comma-sep methods supported at the url and endpoint, e.g. POST
            response = requests.options(url_, timeout=20)
        except Exception:
            response = None

        if response is not None and response.status_code:
            logger.info(
                '[wbia_whaleridgefindr - PASSED CONTAINER URL CHECK] URL %r passed the check'
                % url_
            )
            #headers = response.headers
            # unpack the return from options
            # TODO: generalize this key / iterate across options
            #allow = headers.get('Access-Control-Allow-Methods', '')
            # split up the comma-seperated list (and uppercase)
            #supported_methods_ = [method.strip().upper() for method in allow.split(',')]
            #supported_methods = set(supported_methods_)
            # from our set of required methods, remove each method that is in fact supported
            # assert the result is empty
            #if len(required_methods - supported_methods) == 0:
            flag = True
        if not flag:
            args = (endpoint,)
            logger.info(
                '[wbia_whaleridgefindr - FAILED CONTAINER ENSURE CHECK] Endpoint %r failed the check'
                % args
            )
            logger.info('\tRequired Methods:  %r' % (required_methods,))
            logger.info('\tSupported Methods: %r' % (supported_methods,))
        logger.info('\tFlag: %r' % (flag,))
        flag_list.append(flag)
    supported = np.all(flag_list)
    return supported


docker_control.docker_register_config(
    None,
    'flukebook_whaleridgefindr',
    'haimeh/whaleridgefindr:latest',
    run_args={'_internal_port': 8005, '_external_suggested_port': 8005},
    container_check_func=_wbia_plugin_whaleridgefindr_check_container,
)


@register_ibs_method
def whaleridgefindr_ensure_backend(ibs, container_name='flukebook_whaleridgefindr', clone=None):
    # below code doesn't work bc of wbia-scope issue
    global BACKEND_URL
    if BACKEND_URL is None:
        BACKEND_URLS = ibs.docker_ensure(container_name, clone=clone)
        if len(BACKEND_URLS) == 0:
            raise RuntimeError('Could not ensure container')
        elif len(BACKEND_URLS) == 1:
            BACKEND_URL = BACKEND_URLS[0]
        else:
            BACKEND_URL = BACKEND_URLS[0]
            args = (
                BACKEND_URLS,
                BACKEND_URL,
            )
            logger.info(
                '[WARNING] Multiple BACKEND_URLS:\n\tFound: %r\n\tUsing: %r' % args
            )
    return BACKEND_URL


def whaleridgefindr_feature_extract_aid_helper(url, fpath, retry=3):
    import requests
    import json

    logger.info('Getting whaleridgefindr hash from %s for file %s' % (url, fpath))

    url_ = 'http://%s/ocpu/library/finFindR/R/hashFromImage/json' % (url)

    with open(fpath, 'rb') as image_file:
        post_file = {
            'imageobj': image_file,
        }
        response = requests.post(url_, files=post_file, timeout=120)

    try:
        json_result = json.loads(response.content)
        # check for weird rare case where json_result looks exactly like [{},{}]
        assert isinstance(json_result, dict)
        assert json_result.get('hash', None) is not None
        assert json_result.get('coordinates', None) is not None

    except (json.JSONDecodeError, AssertionError):
        logger.info('------------------')
        logger.info('WHALERIDGEFINDR API ERROR:')
        logger.info(response.content.decode('ascii'))
        logger.info('------------------')
        json_result = None

        # Attempt to try again...
        if retry > 0:
            logger.info('Retrying this request again (retry = %d)' % (retry,))
            new_retry = retry - 1
            json_result = whaleridgefindr_feature_extract_aid_helper(url, fpath, retry=new_retry)

    return json_result


@register_ibs_method
def whaleridgefindr_feature_extract_aid(ibs, aid, **kwargs):
    url = ibs.whaleridgefindr_ensure_backend(**kwargs)
    fpath = ibs.whaleridgefindr_annot_chip_fpath_from_aid(aid)
    json_result = whaleridgefindr_feature_extract_aid_helper(url, fpath)
    return json_result


@register_ibs_method
def whaleridgefindr_feature_extract_aid_batch(ibs, aid_list, jobs=None, **kwargs):

    MAXJOBS = 4

    if jobs is None:
        jobs = ut.num_cpus()

    jobs = min(jobs, len(aid_list))
    jobs = min(jobs, MAXJOBS)

    url_clone_list = []
    for job in range(jobs):
        container_name = 'flukebook_whaleridgefindr'
        urls_clone = ibs.docker_ensure(container_name, clone=job)

        if len(urls_clone) == 0:
            raise RuntimeError('Could not ensure container clone')
        elif len(urls_clone) == 1:
            url_clone = urls_clone[0]
        else:
            url_clone = urls_clone[0]
            args = (
                urls_clone,
                url_clone,
            )
            logger.info(
                '[WARNING] Multiple BACKEND_URLS:\n\tFound: %r\n\tUsing: %r' % args
            )
        url_clone_list.append(url_clone)

    config = {
        'ext': '.jpg',
    }
    fpath_list = ibs.get_annot_chip_fpath(aid_list, ensure=True, config2_=config)

    url_list = []
    index = 0
    for fpath in fpath_list:
        url = url_clone_list[index]
        url_list.append(url)

        index += 1
        index %= len(url_clone_list)

    args_list = list(zip(url_list, fpath_list))

    json_result_gen = ut.generate2(
        whaleridgefindr_feature_extract_aid_helper,
        args_list,
        nTasks=len(args_list),
        nprocs=jobs,
        ordered=True,
    )

    json_result_list = list(json_result_gen)

    return json_result_list


class WhaleRidgeFindRFeatureConfig(dt.Config):  # NOQA
    _param_info_list = []


@register_preproc_annot(
    tablename='WhaleRidgeFindRFeature',
    parents=[ANNOTATION_TABLE],
    colnames=['response'],
    coltypes=[dict],
    configclass=WhaleRidgeFindRFeatureConfig,
    fname='whaleridgefindr',
    chunksize=128,
)
def whaleridgefindr_feature_extract_aid_depc(depc, aid_list, config):
    # The doctest for wbia_plugin_deepsense_identify_deepsense_ids also covers this func
    ibs = depc.controller
    OLD = True
    if OLD:
        # Compute the features one at a time
        for aid in aid_list:
            response = ibs.whaleridgefindr_feature_extract_aid(aid)
            yield (response,)
    else:
        # Compute the features in small batches (for multi-container processing)
        response_list = ibs.whaleridgefindr_feature_extract_aid_batch(aid_list)
        for response in response_list:
            yield (response,)


@register_ibs_method
@register_api('/api/plugin/finfindr/feature/', methods=['GET'])
def whaleridgefindr_feature_extract(ibs, annot_uuid, use_depc=True, config={}, **kwargs):
    r"""
    Gets the whaleridgefindr feature representation of an annot

    CommandLine:
        python -m wbia_whaleridgefindr._plugin --test-whaleridgefindr_feature_extract
        python -m wbia_whaleridgefindr._plugin --test-whaleridgefindr_feature_extract:0

    Example:
        >>> # DISABLE_DOCTEST
        >>> import utool as ut
        >>> import wbia_whaleridgefindr
        >>> import wbia
        >>> from wbia.init import sysres
        >>> # The curvrank testdb also uses dolphin dorsals
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = wbia.opendb(dbdir=dbdir)
        >>> aid_list = ibs.get_image_aids(1)
        >>> annot_uuid = ibs.get_annot_uuids(aid_list)[0]
        >>> feature = ibs.whaleridgefindr_feature_extract(annot_uuid, use_depc=False)
        >>> feature_depc = ibs.whaleridgefindr_feature_extract(annot_uuid)
        >>> assert feature == feature_depc
        >>> result = feature
        >>> print(result)
        {'hash': [[31.7485, -145.0079, 152.3881, -20.2424, -112.6928, -92.4987, -166.5634, 12.4394, 15.0508, -146.4167, 97.4581, -146.8563, 89.4078, 213.0233, 43.8438, -58.0497, -89.5602, 198.5325, 38.7556, 38.5446, -173.2831, 293.7115, -204.0254, -92.9775, -157.026, 64.4671, 11.6679, -200.2824, -225.0971, -75.7923, 268.0069, -72.0642]], 'coordinates': [[243, 93], [242, 93], [242, 93], [242, 94], [241, 94], [241, 94], [241, 94], [240, 94], [240, 94], [240, 94], [239, 94], [239, 94], [239, 94], [239, 95], [238, 95], [238, 95], [238, 95], [237, 95], [237, 95], [237, 95], [236, 95], [236, 96], [236, 96], [235, 96], [235, 96], [235, 96], [234, 96], [234, 96], [234, 97], [233, 97], [233, 97], [233, 97], [233, 97], [232, 98], [232, 98], [232, 98], [231, 98], [231, 98], [231, 98], [230, 98], [230, 99], [230, 99], [229, 99], [229, 99], [229, 100], [228, 100], [228, 100], [228, 100], [228, 101], [227, 101], [227, 101], [227, 102], [226, 102], [226, 102], [226, 102], [225, 103], [225, 103], [225, 103], [225, 103], [225, 104], [224, 104], [224, 104], [224, 105], [224, 105], [223, 105], [223, 106], [223, 106], [223, 106], [223, 107], [223, 107], [223, 107], [222, 108], [222, 108], [222, 108], [222, 108], [222, 109], [222, 109], [222, 109], [222, 110], [221, 110], [221, 110], [221, 111], [221, 111], [221, 111], [221, 112], [221, 112], [221, 112], [221, 113], [221, 113], [221, 113], [222, 113], [222, 114], [222, 114], [222, 114], [222, 115], [222, 115], [222, 115], [222, 116], [222, 116], [223, 116], [223, 117], [223, 117], [223, 117], [223, 118], [223, 118], [223, 118], [223, 119], [223, 119], [223, 119], [223, 119], [224, 120], [224, 120], [224, 120], [224, 121], [224, 121], [224, 121], [224, 122], [224, 122], [224, 122], [225, 123], [225, 123], [225, 123], [225, 124], [225, 124], [225, 124], [225, 124], [225, 125], [226, 125], [226, 125], [226, 126], [226, 126], [226, 126], [226, 127], [226, 127], [227, 127], [227, 128], [227, 128], [227, 128], [227, 129], [227, 129], [227, 129], [228, 129], [228, 130], [228, 130], [228, 130], [228, 131], [228, 131], [228, 131], [228, 132], [228, 132], [229, 132], [229, 133], [229, 133], [229, 133], [229, 134], [229, 134], [229, 134], [230, 134], [230, 135], [230, 135], [230, 135], [230, 136], [230, 136], [230, 136], [231, 137], [231, 137], [231, 137], [231, 138], [231, 138], [231, 138], [231, 139], [231, 139], [232, 139], [232, 140], [232, 140], [232, 140], [232, 140], [232, 141], [232, 141], [232, 141], [232, 142], [233, 142], [233, 142], [233, 143], [233, 143], [233, 143], [233, 144], [233, 144], [233, 144], [233, 145], [233, 145], [234, 145], [234, 145], [234, 146], [234, 146], [234, 146], [234, 147], [234, 147], [234, 147], [234, 148], [235, 148], [235, 148], [235, 149], [235, 149], [235, 149], [235, 150], [235, 150], [235, 150], [235, 150], [235, 151], [236, 151], [236, 151], [236, 152], [236, 152], [236, 152], [236, 153], [236, 153], [236, 153], [236, 154], [237, 154], [237, 154], [237, 155], [237, 155], [237, 155], [237, 155], [237, 156], [237, 156], [237, 156], [238, 157], [238, 157], [238, 157], [238, 158], [238, 158], [238, 158], [238, 159], [238, 159], [238, 159], [238, 160], [238, 160], [238, 160], [238, 160], [239, 161], [239, 161], [239, 161], [239, 162], [239, 162], [239, 162], [239, 163], [239, 163], [239, 163], [239, 164], [239, 164], [239, 164], [239, 165], [239, 165], [239, 165], [240, 166], [240, 166], [240, 166], [240, 166], [240, 167], [240, 167], [240, 167], [240, 168], [240, 168], [240, 168], [240, 169], [240, 169], [241, 169], [241, 170], [241, 170], [241, 170], [241, 171], [241, 171], [241, 171], [241, 171], [241, 172], [241, 172], [241, 172], [241, 173], [242, 173], [242, 173], [242, 174], [242, 174], [242, 174], [242, 175], [242, 175], [242, 175], [242, 176], [242, 176], [242, 176], [242, 176], [242, 177], [242, 177], [242, 177], [242, 178], [242, 178], [242, 178], [242, 179], [242, 179], [242, 179], [242, 180], [242, 180], [242, 180], [242, 181], [242, 181], [242, 181], [242, 181], [243, 182], [243, 182], [243, 182], [243, 183], [243, 183], [243, 183], [243, 184], [243, 184], [243, 184], [243, 185], [243, 185], [243, 185], [243, 186], [243, 186], [243, 186], [243, 187], [244, 187], [244, 187], [244, 187], [244, 188], [244, 188], [244, 188], [244, 189], [244, 189], [244, 189], [244, 190], [244, 190], [244, 190], [244, 191], [244, 191], [244, 191], [244, 192], [244, 192], [244, 192], [244, 192], [244, 193], [244, 193], [244, 193], [244, 194], [244, 194], [244, 194], [244, 195], [244, 195], [244, 195], [244, 196], [244, 196], [244, 196], [244, 197], [244, 197], [244, 197], [245, 197], [245, 198], [245, 198], [245, 198], [245, 199], [245, 199], [245, 199], [245, 200], [245, 200], [245, 200], [245, 201], [245, 201], [245, 201], [245, 202], [245, 202], [245, 202], [245, 202], [245, 203], [245, 203], [245, 203], [245, 204], [245, 204], [245, 204], [245, 205], [245, 205], [245, 205], [245, 206], [245, 206], [245, 206], [245, 207], [245, 207], [245, 207], [245, 207], [245, 208], [245, 208], [245, 208], [245, 209], [245, 209], [245, 209], [245, 210], [245, 210], [245, 210], [245, 211], [245, 211], [245, 211], [245, 212], [245, 212], [245, 212], [245, 213], [245, 213], [245, 213], [245, 213], [244, 214], [244, 214], [244, 214], [244, 215], [244, 215], [244, 215], [244, 216], [244, 216], [244, 216], [244, 217], [244, 217], [244, 217], [244, 218], [244, 218], [244, 218], [244, 218], [244, 219], [244, 219], [244, 219], [244, 220], [244, 220], [244, 220], [244, 221], [244, 221], [244, 221], [244, 222], [244, 222], [244, 222], [244, 223], [244, 223], [244, 223], [244, 223], [244, 224], [244, 224], [244, 224], [244, 225], [244, 225], [244, 225], [244, 226], [244, 226], [244, 226], [244, 227], [244, 227], [244, 227], [244, 228], [244, 228], [244, 228], [244, 228], [244, 229], [244, 229], [244, 229], [244, 230], [244, 230], [244, 230], [244, 231], [244, 231], [244, 231], [243, 232], [243, 232], [243, 232], [243, 233], [243, 233], [243, 233], [243, 234], [243, 234], [243, 234], [243, 234], [243, 235], [243, 235], [243, 235], [243, 236], [243, 236], [243, 236], [243, 237], [243, 237], [243, 237], [243, 238], [243, 238], [243, 238], [243, 239], [243, 239], [243, 239], [243, 239], [243, 240], [242, 240], [242, 240], [242, 241], [242, 241], [242, 241], [242, 242], [242, 242], [242, 242], [242, 243], [242, 243], [242, 243], [242, 244], [242, 244], [242, 244], [242, 244], [242, 245], [242, 245], [241, 245], [241, 246], [241, 246], [241, 246], [241, 247], [241, 247], [241, 247], [241, 248], [241, 248], [241, 248], [241, 249], [241, 249], [241, 249], [241, 249], [241, 250], [241, 250], [241, 250], [241, 251], [241, 251], [241, 251], [241, 252], [241, 252], [241, 252], [241, 253], [241, 253], [240, 253], [240, 254], [240, 254], [240, 254], [239, 254], [239, 255], [239, 255], [239, 255], [239, 256], [239, 256], [238, 256], [238, 257], [238, 257], [238, 257], [237, 258], [237, 258], [237, 258], [236, 259], [236, 259], [236, 259], [236, 260], [235, 260], [235, 260], [235, 260], [235, 261], [234, 261], [234, 261], [234, 262], [234, 262], [234, 262], [234, 263], [234, 263], [234, 263], [234, 264], [235, 264], [235, 264], [235, 265], [236, 265], [236, 265], [236, 265], [237, 265], [237, 265], [237, 266], [238, 266], [238, 266], [238, 266], [239, 266], [239, 266], [239, 267], [239, 267], [240, 267], [240, 267], [240, 268], [241, 268], [241, 268], [241, 269], [242, 269], [242, 269], [242, 270], [243, 270], [243, 270], [243, 270], [244, 271], [244, 271], [244, 271], [244, 272], [245, 272], [245, 272], [245, 273], [246, 273], [246, 273], [246, 273], [247, 274], [247, 274], [247, 274], [247, 275], [247, 275], [247, 275], [247, 275], [247, 276], [247, 276], [247, 276], [247, 277], [246, 277], [246, 277], [246, 278], [246, 278], [245, 278], [245, 279], [245, 279], [245, 279], [246, 280], [246, 280], [246, 280], [246, 281], [246, 281], [247, 281], [247, 281], [247, 282], [247, 282], [247, 282], [247, 283], [247, 283], [246, 283], [246, 284], [246, 284], [245, 284], [245, 283], [245, 283], [244, 283], [244, 282], [244, 282], [244, 283], [243, 283], [243, 283], [243, 284], [242, 284], [242, 284], [242, 285], [241, 285], [241, 285], [241, 285], [240, 285], [240, 285], [240, 286], [239, 286], [239, 286], [239, 285], [239, 285], [238, 285], [238, 285], [238, 285], [237, 285], [237, 285], [237, 285], [236, 285], [236, 285], [236, 285], [235, 285], [235, 284], [235, 284], [234, 284], [234, 283], [234, 283], [233, 284], [233, 283], [233, 283], [233, 283], [232, 283], [232, 283], [232, 282], [231, 282], [231, 282], [231, 282], [230, 281], [230, 281], [230, 281], [229, 282], [229, 282], [229, 282], [228, 282], [228, 283], [228, 283], [228, 283], [227, 283], [227, 284], [227, 284], [226, 284], [226, 285], [226, 285], [225, 285], [225, 286], [225, 286], [224, 286], [224, 286], [224, 287], [223, 287], [223, 287], [223, 288], [223, 288], [223, 288], [223, 289], [223, 289], [223, 289], [223, 290], [223, 290], [224, 290], [224, 291], [224, 291], [225, 291], [225, 291], [225, 292], [226, 292], [226, 292], [226, 293], [226, 293], [226, 293], [226, 294], [226, 294], [226, 294], [226, 295], [225, 295], [225, 295], [225, 296], [224, 296], [224, 296], [224, 296], [223, 297], [223, 297], [223, 297], [223, 298], [222, 298], [222, 298], [222, 298], [221, 299], [221, 299], [221, 299], [220, 299], [220, 300], [220, 300], [219, 300], [219, 301], [219, 301], [218, 301], [218, 301], [218, 301], [218, 301], [217, 302], [217, 302], [217, 302], [216, 302], [216, 302], [216, 303], [215, 303], [215, 303], [215, 303], [214, 304], [214, 304], [214, 304], [213, 304], [213, 305], [213, 305], [213, 305], [212, 305], [212, 306], [212, 306], [211, 306], [211, 306], [211, 307], [210, 307], [210, 307], [210, 307], [209, 307], [209, 307], [209, 308], [208, 308], [208, 308], [208, 308], [207, 309]]}

    """
    aid = ibs.get_annot_aids_from_uuid([annot_uuid])[0]
    if use_depc:
        response_list = ibs.depc_annot.get(
            'WhaleRidgeFindRFeature', [aid], 'response', config=config
        )
        response = response_list[0]
    else:
        response = ibs.whaleridgefindr_feature_extract_aid(aid)
    return response


@register_ibs_method
def wbia_plugin_whaleridgefindr_identify(
    ibs, qaid_list, daid_list, use_depc=True, config={}, **kwargs
):
    r"""
    Matches qaid_list against daid_list using whaleridgefindr

    CommandLine:
        python -m wbia_whaleridgefindr._plugin --test-wbia_plugin_whaleridgefindr_identify
        python -m wbia_whaleridgefindr._plugin --test-wbia_plugin_whaleridgefindr_identify:0

    Example:
        >>> # DISABLE_DOCTEST
        >>> import utool as ut
        >>> import wbia_whaleridgefindr
        >>> from wbia_whaleridgefindr._plugin import whaleridgefindrRequest
        >>> import wbia
        >>> from wbia.init import sysres
        >>> # The curvrank testdb also uses dolphin dorsals
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = wbia.opendb(dbdir=dbdir)
        >>> depc = ibs.depc_annot
        >>> qaid = [1]
        >>> daid_list = [2, 3, 4, 5]
        >>> qaid_list_clean, daid_list_clean, response = ibs.wbia_plugin_whaleridgefindr_identify(qaid, daid_list)
        >>> assert response.status_code == 201
        >>> result = response.text
        >>> print(result)
        {
          "distances": [
            {
              "V1": 217.5667,
              "V2": 532.0134,
              "V3": 651.7316,
              "V4": 725.5806
            }
          ],
          "sortingIndex": [
            {
              "V1": 1,
              "V2": 2,
              "V3": 4,
              "V4": 3
            }
          ]
        }
    """
    qaid_list = sorted(qaid_list)
    daid_list = sorted(daid_list)

    q_feature_dict = ibs.whaleridgefindr_aid_feature_dict(qaid_list, skip_failures=True)
    d_feature_dict = ibs.whaleridgefindr_aid_feature_dict(daid_list, skip_failures=True)

    qaid_list_clean = list(q_feature_dict.keys())
    daid_list_clean = list(d_feature_dict.keys())

    num_qaid_clean = len(qaid_list_clean)
    num_daid_clean = len(daid_list_clean)

    logger.info(
        '[whaleridgefindr] Retrieved features for %d qaids, %d daids'
        % (len(qaid_list), len(daid_list))
    )
    logger.info('[whaleridgefindr] \tClean qaids: %d' % (num_qaid_clean,))
    logger.info('[whaleridgefindr] \tClean daids: %d' % (num_daid_clean,))

    if 0 in [num_qaid_clean, num_daid_clean]:
        response = None
    else:
        whaleridgefindr_arg_dict = {}
        whaleridgefindr_arg_dict['queryHashData'] = q_feature_dict
        whaleridgefindr_arg_dict['referenceHashData'] = d_feature_dict
        whaleridgefindr_arg_dict['justIndex'] = 1
        whaleridgefindr_arg_dict['batchSize'] = 1

        url = ibs.whaleridgefindr_ensure_backend(**kwargs)
        url = 'http://%s/ocpu/library/finFindR/R/distanceToRefParallel/json' % (url)

        response = requests.post(url, json=whaleridgefindr_arg_dict)

    return qaid_list_clean, daid_list_clean, response


# this method takes an aid_list and returns the arguments whaleridgefindr needs to do matching for those aid[p]
@register_ibs_method
def whaleridgefindr_aid_feature_dict(ibs, aid_list, skip_failures=False):
    r"""
    Constructs the {aid0: feature0, aid1: feature1,...} dict that the whaleridgefindr api
    takes as input for its distance func

    CommandLine:
        python -m wbia_whaleridgefindr._plugin --test-whaleridgefindr_aid_feature_dict
        python -m wbia_whaleridgefindr._plugin --test-whaleridgefindr_aid_feature_dict:0

    Example:
        >>> # DISABLE_DOCTEST
        >>> import utool as ut
        >>> import wbia_whaleridgefindr
        >>> from wbia_whaleridgefindr._plugin import whaleridgefindrRequest
        >>> import wbia
        >>> from wbia.init import sysres
        >>> # The curvrank testdb also uses dolphin dorsals
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = wbia.opendb(dbdir=dbdir)
        >>> depc = ibs.depc_annot
        >>> aid_list = [1, 2]
        >>> result = ibs.whaleridgefindr_aid_feature_dict(aid_list)
        >>> print(result)
        {1: [31.7485, -145.0079, 152.3881, -20.2424, -112.6928, -92.4987, -166.5634, 12.4394, 15.0508, -146.4167, 97.4581, -146.8563, 89.4078, 213.0233, 43.8438, -58.0497, -89.5602, 198.5325, 38.7556, 38.5446, -173.2831, 293.7115, -204.0254, -92.9775, -157.026, 64.4671, 11.6679, -200.2824, -225.0971, -75.7923, 268.0069, -72.0642], 2: [-12.9609, -141.8752, 146.1252, -10.9072, -74.338, -81.2214, -212.8647, -55.3229, -7.7403, -192.7125, 27.3991, -113.9109, 96.7002, 185.7276, 73.1729, -70.496, -100.3558, 151.6967, -2.8725, 101.6979, -257.0346, 296.2685, -228.557, -40.953, -137.485, 46.1819, 8.2551, -251.8766, -224.5837, -18.7147, 239.0382, -48.6348]}
    """
    global GLOBAL_FEATURE_IN_MEMORY_CACHE

    dirty_aid_list = []
    for aid in aid_list:
        if aid not in GLOBAL_FEATURE_IN_MEMORY_CACHE:
            dirty_aid_list.append(aid)

    dirty_hash_data_list = ibs.depc_annot.get(
        'whaleridgefindrFeature', dirty_aid_list, 'response'
    )
    zipped = zip(dirty_aid_list, dirty_hash_data_list)
    for dirty_aid, dirty_hash_data in zipped:
        GLOBAL_FEATURE_IN_MEMORY_CACHE[dirty_aid] = dirty_hash_data

    for aid in aid_list:
        assert aid in GLOBAL_FEATURE_IN_MEMORY_CACHE

    annot_hash_data = ut.take(GLOBAL_FEATURE_IN_MEMORY_CACHE, aid_list)

    aid_hash_dict = {}
    for aid, hash_data in zip(aid_list, annot_hash_data):
        # hash_result comes from whaleridgefindr in this format

        if hash_data is None:
            hash_ = None
        elif isinstance(hash_data, list):
            hash_ = None
        else:
            hash_ = hash_data.get('hash', [])
            if len(hash_) > 0:
                hash_ = hash_[0]

        if hash_ is None and skip_failures:
            continue

        assert aid not in aid_hash_dict
        aid_key = '%08d' % aid
        aid_hash_dict[aid_key] = hash_

    return aid_hash_dict


class whaleridgefindrDistanceConfig(dt.Config):  # NOQA
    _param_info_list = []


@register_preproc_annot(
    tablename='whaleridgefindrDistance',
    parents=[ANNOTATION_TABLE, ANNOTATION_TABLE],
    colnames=['distance'],
    coltypes=[float],
    configclass=whaleridgefindrDistanceConfig,
    fname='whaleridgefindr',
    chunksize=None,
)
def whaleridgefindr_distance_depc(depc, qaid_list, daid_list, config):
    # qaid and aid lists are parallel
    # The doctest for wbia_plugin_deepsense_identify_deepsense_ids also covers this func
    ibs = depc.controller

    qaids = list(set(qaid_list))
    assert len(qaids) == 1
    daids = list(set(daid_list))

    qaids_clean, daids_clean, response = ibs.wbia_plugin_whaleridgefindr_identify(qaids, daids)
    distance_dict = ibs.whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(
        qaids, daids, qaids_clean, daids_clean, response
    )

    zipped = list(zip(qaid_list, daid_list))
    for qaid, daid in zipped:
        distance = distance_dict.get(daid, None)
        yield (distance,)


# assuming there was only one qaid, we don't need it for this step
@register_ibs_method
def whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(
    ibs, qaid_list, daid_list, qaid_list_clean, daid_list_clean, response, query_no=0
):
    r"""
    whaleridgefindr returns match results in a strange format. This func converts that
    to wbia's familiar score list.

    Args:
        daid_list: list of daids originally sent to whaleridgefindr
        response: the response from whaleridgefindr; output of wbia_plugin_whaleridgefindr_identify

    CommandLine:
        python -m wbia_whaleridgefindr._plugin --test-whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result
        python -m wbia_whaleridgefindr._plugin --test-whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result:0

    Example:
        >>> # DISABLE_DOCTEST
        >>> import utool as ut
        >>> import wbia_whaleridgefindr
        >>> import wbia
        >>> from wbia.init import sysres
        >>> # The curvrank testdb also uses dolphin dorsals
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = wbia.opendb(dbdir=dbdir)
        >>> depc = ibs.depc_annot
        >>> qaid = [1]
        >>> daid_list = [2, 3, 4, 5]
        >>> qaid_list_clean, daid_list_clean, id_response = ibs.wbia_plugin_whaleridgefindr_identify(qaid, daid_list)
        >>> result = ibs.whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(qaid, daid_list, qaid_list_clean, daid_list_clean, id_response)
        >>> print(result)
        [217.5667, 532.0134, 725.5806, 651.7316]
    """
    distance_dict = {}

    try:
        # It's possible that response is None (caught API failure) or it's due to a parse error
        response_dict = response.json()

        # Get values from the API response
        sortingIndex = response_dict['sortingIndex'][query_no]
        distances = response_dict['distances'][query_no]

        key_list = sorted(list(sortingIndex.keys()))
        for key in key_list:
            assert key in distances
            index = sortingIndex.get(key, None)
            distance = distances.get(key, None)
            if index is None:
                continue
            index -= 1
            daid_clean_str = daid_list_clean[index]
            # casting daids back-forth bc whaleridgefindr sorts lexigraphically on string keys
            daid_clean = int(daid_clean_str)
            distance_dict[daid_clean] = distance
    except Exception:
        pass

    return distance_dict


@register_ibs_method
def whaleridgefindr_passport(ibs, aid, output=False, config={}, **kwargs):

    annot_hash_data = ibs.depc_annot.get(
        'whaleridgefindrFeature', [aid], 'response', config=config
    )
    hash_data = annot_hash_data[0]

    if hash_data is None:
        edge_coords = None
    else:
        edge_coords = hash_data['coordinates']

    image_path = ibs.whaleridgefindr_annot_chip_fpath_from_aid(aid)
    pil_image = Image.open(image_path)

    # we now modify pil_image and save it elsewhere when we're done
    draw = ImageDraw.Draw(pil_image)
    # convert edge_coords to the format draw.line is looking for

    if edge_coords is not None:
        edge_coord_tuples = [(coord[0], coord[1]) for coord in edge_coords]
        # TODO: Add start and end dot to show directionality
        draw.line(xy=edge_coord_tuples, fill='yellow', width=3)

    if output:
        local_path = dirname(abspath(__file__))
        output_path = abspath(join(local_path, '..', '_output'))
        ut.ensuredir(output_path)
        output_filepath_fmtstr = join(output_path, 'passport-%s.png')
        # TODO: save to UUID not aid
        # output_filepath = output_filepath_fmtstr % (annot_uuid, )
        output_filepath = output_filepath_fmtstr % (aid,)
        logger.info('Writing to %s' % (output_filepath,))
        pil_image.save(output_filepath)

    return pil_image


# TODO: ask JP if it's kosher to duplicate this func also defined in wbia-deepsense-module
def pil_image_load(absolute_path):
    pil_img = Image.open(absolute_path)
    return pil_img


def pil_image_write(absolute_path, pil_img):
    pil_img.save(absolute_path)  # error on this line as it tries to save it as .cpkl


class whaleridgefindrPassportConfig(dt.Config):  # NOQA
    _param_info_list = [
        # TODO: is dim_size necessary?
        ut.ParamInfo('dim_size', DIM_SIZE),
        ut.ParamInfo('ext', '.jpg'),
    ]


@register_preproc_annot(
    tablename='whaleridgefindrPassport',
    parents=[ANNOTATION_TABLE],
    colnames=['image'],
    coltypes=[('extern', pil_image_load, pil_image_write)],
    configclass=whaleridgefindrPassportConfig,
    fname='whaleridgefindr',
    chunksize=128,
)
def whaleridgefindr_passport_depc(depc, aid_list, config):
    # The doctest for wbia_plugin_deepsense_identify_deepsense_ids also covers this func
    ibs = depc.controller
    for aid in aid_list:
        image = ibs.whaleridgefindr_passport(aid, config=config)
        yield (image,)


@register_route(
    '/api/plugin/finfindr/passport/src/<aid>/',
    methods=['GET'],
    __route_prefix_check__=False,
    __route_authenticate__=False,
)
def whaleridgefindr_passport_src(aid=None, ibs=None, **kwargs):
    from six.moves import cStringIO as StringIO
    from io import BytesIO
    from PIL import Image  # NOQA
    from flask import current_app, send_file
    from wbia.web import appfuncs as appf
    import six

    if ibs is None:
        ibs = current_app.ibs

    aid = int(aid)
    aid_list = [aid]
    passport_paths = ibs.depc_annot.get(
        'whaleridgefindrPassport', aid_list, 'image', read_extern=False, ensure=True
    )
    passport_path = passport_paths[0]

    # Load image
    assert passport_paths is not None, 'passport path should not be None'
    image = vt.imread(passport_path, orient='auto')
    image = appf.resize_via_web_parameters(image)
    image = image[:, :, ::-1]

    # Encode image
    image_pil = Image.fromarray(image)
    if six.PY2:
        img_io = StringIO()
    else:
        img_io = BytesIO()
    image_pil.save(img_io, 'JPEG', quality=100)
    img_io.seek(0)

    return send_file(img_io, mimetype='image/jpeg')


# TODO: move this into the wbia package. Literally copy-pasted from deepsense right now
@register_ibs_method
def whaleridgefindr_aid_list_from_annot_uuid_list(ibs, annot_uuid_list):
    # do we need to do the following check?
    # ibs.web_check_uuids(qannot_uuid_list=annot_uuid_list)
    # Ensure annotations
    annot_uuid_list = ensure_uuid_list(annot_uuid_list)
    aid_list = ibs.get_annot_aids_from_uuid(annot_uuid_list)
    return aid_list


# TODO: does this work and is this the desired config for whaleridgefindr
@register_ibs_method
def whaleridgefindr_annot_chip_fpath(ibs, annot_uuid, **kwargs):
    aid = ibs.whaleridgefindr_aid_from_annot_uuid(annot_uuid)
    return ibs.whaleridgefindr_annot_chip_fpath_from_aid(aid, **kwargs)


@register_ibs_method
def whaleridgefindr_annot_chip_fpath_from_aid(ibs, aid, **kwargs):
    config = {
        'ext': '.jpg',
    }
    fpath = ibs.get_annot_chip_fpath(aid, ensure=True, config2_=config)
    return fpath


@register_ibs_method
def whaleridgefindr_aid_from_annot_uuid(ibs, annot_uuid):
    annot_uuid_list = [annot_uuid]
    ibs.web_check_uuids(qannot_uuid_list=annot_uuid_list)
    annot_uuid_list = ensure_uuid_list(annot_uuid_list)
    # Ensure annotations
    aid_list = ibs.get_annot_aids_from_uuid(annot_uuid_list)
    aid = aid_list[0]
    return aid


@register_ibs_method
def whaleridgefindr_init_testdb(ibs):
    image_path = abspath('/home/wildme/code/wbia-whaleridgefindr-module/example-images')
    assert exists(image_path)
    gid_list = ibs.import_folder(image_path, ensure_loadable=False, ensure_exif=False)
    uri_list = ibs.get_image_uris_original(gid_list)
    fname_list = [split(uri)[1] for uri in uri_list]
    # annot_name_list not using splitext but split('.') so we can get mult images per indiv.
    annot_name_list = [fname.split('.')[0] for fname in fname_list]
    aid_list = ibs.use_images_as_annotations(gid_list)
    ibs.set_annot_names(aid_list, annot_name_list)
    return gid_list, aid_list


# this func is called reflexively and identical to get_match_results in deepsense and curvrank
def get_match_results(depc, qaid_list, daid_list, score_list, config):
    """converts table results into format for ipython notebook"""
    # qaid_list, daid_list = request.get_parent_rowids()
    # score_list = request.score_list
    # config = request.config

    unique_qaids, groupxs = ut.group_indices(qaid_list)
    # grouped_qaids_list = ut.apply_grouping(qaid_list, groupxs)
    grouped_daids = ut.apply_grouping(daid_list, groupxs)
    grouped_scores = ut.apply_grouping(score_list, groupxs)

    ibs = depc.controller
    unique_qnids = ibs.get_annot_nids(unique_qaids)

    # scores
    _iter = zip(unique_qaids, unique_qnids, grouped_daids, grouped_scores)
    for qaid, qnid, daids, scores in _iter:
        dnids = ibs.get_annot_nids(daids)

        # Remove distance to self
        annot_scores = np.array(scores)
        daid_list_ = np.array(daids)
        dnid_list_ = np.array(dnids)

        is_valid = daid_list_ != qaid
        daid_list_ = daid_list_.compress(is_valid)
        dnid_list_ = dnid_list_.compress(is_valid)
        annot_scores = annot_scores.compress(is_valid)

        # Hacked in version of creating an annot match object
        match_result = wbia.AnnotMatch()
        match_result.qaid = qaid
        match_result.qnid = qnid
        match_result.daid_list = daid_list_
        match_result.dnid_list = dnid_list_
        match_result._update_daid_index()
        match_result._update_unique_nid_index()

        grouped_annot_scores = vt.apply_grouping(annot_scores, match_result.name_groupxs)
        name_scores = np.array([np.sum(dists) for dists in grouped_annot_scores])
        match_result.set_cannonical_name_score(annot_scores, name_scores)
        yield match_result


class whaleridgefindrConfig(dt.Config):  # NOQA
    """
    CommandLine:
        python -m wbia_deepsense._plugin --test-whaleridgefindrConfig

    Example:
        >>> # DISABLE_DOCTEST
        >>> from wbia_whaleridgefindr._plugin import *  # NOQA
        >>> config = whaleridgefindrConfig()
        >>> result = config.get_cfgstr()
        >>> print(result)
        whaleridgefindr(dim_size=2000)
    """

    def get_param_info_list(self):
        return [
            ut.ParamInfo('dim_size', DIM_SIZE),
        ]


class whaleridgefindrRequest(dt.base.VsOneSimilarityRequest):
    _symmetric = False
    _tablename = 'whaleridgefindr'

    @ut.accepts_scalar_input
    def get_fmatch_overlayed_chip(request, aid_list, config=None):
        depc = request.depc
        ibs = depc.controller
        passport_paths = ibs.depc_annot.get(
            'whaleridgefindrPassport',
            aid_list,
            'image',
            config=config,
            read_extern=False,
            ensure=True,
        )
        passports = list(map(vt.imread, passport_paths))
        return passports

    def render_single_result(request, cm, aid, **kwargs):
        # HACK FOR WEB VIEWER
        chips = request.get_fmatch_overlayed_chip([cm.qaid, aid], config=request.config)
        out_img = vt.stack_image_list(chips)
        return out_img

    def postprocess_execute(request, table, parent_rowids, rowids, result_list):
        qaid_list, daid_list = list(zip(*parent_rowids))
        score_list = ut.take_column(result_list, 0)
        depc = request.depc
        config = request.config
        cm_list = list(get_match_results(depc, qaid_list, daid_list, score_list, config))
        table.delete_rows(rowids)

        # Extra cleanup for whaleridgefindrDistance
        ibs = depc.controller
        for table_ in ibs.depc_annot.tables:
            if table_.tablename == 'whaleridgefindrDistance':
                rowids_ = table_.get_rowid(parent_rowids, config=request.config)
                table_.delete_rows(rowids_)

        return cm_list

    def execute(request, *args, **kwargs):
        # kwargs['use_cache'] = False
        result_list = super(whaleridgefindrRequest, request).execute(*args, **kwargs)
        qaids = kwargs.pop('qaids', None)
        # TODO: is this filtering necessary?
        if qaids is not None:
            result_list = [result for result in result_list if result.qaid in qaids]
        return result_list


@register_preproc_annot(
    tablename='whaleridgefindr',
    parents=[ANNOTATION_TABLE, ANNOTATION_TABLE],
    colnames=['score'],
    coltypes=[float],
    configclass=whaleridgefindrConfig,
    requestclass=whaleridgefindrRequest,
    fname='whaleridgefindr',
    rm_extern_on_delete=True,
    chunksize=None,
)
def wbia_plugin_whaleridgefindr(depc, qaid_list, daid_list, config):
    r"""
    Matches qaid_list against daid_list using whaleridgefindr

    CommandLine:
        python -m wbia_whaleridgefindr._plugin --exec-wbia_plugin_whaleridgefindr
        python -m wbia_whaleridgefindr._plugin --exec-wbia_plugin_whaleridgefindr:0

    Example:
        >>> # DISABLE_DOCTEST
        >>> import utool as ut
        >>> import wbia_whaleridgefindr
        >>> from wbia_whaleridgefindr._plugin import whaleridgefindrRequest
        >>> import wbia
        >>> from wbia.init import sysres
        >>> # The curvrank testdb also uses dolphin dorsals
        >>> dbdir = sysres.ensure_testdb_curvrank()
        >>> ibs = wbia.opendb(dbdir=dbdir)
        >>> depc = ibs.depc_annot
        >>> daid_list = [2, 3, 4, 5]
        >>> qaid = [1]
        >>> request = whaleridgefindrRequest.new(depc, qaid, daid_list)
        >>> result = request.execute()
        >>> am = result[0]
        >>> unique_nids = am.unique_nids
        >>> # TODO: run this past JP. The following line seems logic-bugged? the name score per name is just the sum of its annot scores. What a crazy bias that introduces for highly-sighted individuals.
        >>> name_score_list = am.name_score_list
        >>> unique_name_text_list = ibs.get_name_texts(unique_nids)
        >>> name_score_list_ = ['%0.04f' % (score, ) for score in am.name_score_list]
        >>> name_distance_dict = dict(zip(unique_name_text_list, name_score_list_))
        >>> result = name_distance_dict
        >>> print(result)
        {'F272': '0.8045', 'F274': '1.0715', 'F276': '0.5211'}

    """
    # this is going to load the distances from the distance cache and convert those to scores a la Flukematch

    ibs = depc.controller
    distances = ibs.depc_annot.get(
        'whaleridgefindrDistance', (qaid_list, daid_list), 'distance', config=config
    )
    for distance in distances:
        # I'm still confused about these trailing commas. Are we casting this to a unary tuple?
        score = whaleridgefindr_distance_to_match_score(distance)
        yield (score,)


def whaleridgefindr_distance_to_match_score(distance, max_distance_scalar=500.0):
    if distance is None:
        score = 0.0
    else:
        score = np.exp(-1.0 * distance / max_distance_scalar)
    score = max(0.0, score)
    return score


def whaleridgefindr_double_check(ibs, qaid_list, daid_list):
    qaids = list(set(qaid_list))
    daids = list(set(daid_list))
    qaids_clean, daids_clean, response = ibs.wbia_plugin_whaleridgefindr_identify(
        qaids, daids, use_depc=False
    )
    sorted_scores = ibs.whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(
        qaids, daids, qaids_clean, daids_clean, response
    )
    sorted_scores_ = []
    for i in range(len(daid_list)):
        daids_ = [daid_list[i]]
        qaids_clean_, daids_clean_, response_ = ibs.wbia_plugin_whaleridgefindr_identify(
            qaids, daids_, use_depc=False
        )
        score = ibs.whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(
            qaids, daids_, qaids_clean_, daids_clean_, response_
        )[0]
        sorted_scores_.append(score)
    return sorted_scores, sorted_scores_


@register_ibs_method
def whaleridgefindr_double_check_random_order(ibs, qaid_list, daid_list):
    qaids = list(set(qaid_list))
    daids = list(set(daid_list))
    qaids_clean, daids_clean, response = ibs.wbia_plugin_whaleridgefindr_identify(
        qaids, daids, use_depc=False
    )
    sorted_scores = ibs.whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(
        qaids, daids, qaids_clean, daids_clean, response
    )
    sorted_scores_ = []
    for i in range(len(daid_list)):
        daids_ = [daid_list[i]]
        qaids_clean_, daids_clean_, response_ = ibs.wbia_plugin_whaleridgefindr_identify(
            qaids, daids_, use_depc=False
        )
        score = ibs.whaleridgefindr_wbia_distance_list_from_whaleridgefindr_result(
            qaids, daids_, qaids_clean_, daids_clean_, response_
        )[0]
        sorted_scores_.append(score)
    return sorted_scores, sorted_scores_


if __name__ == '__main__':
    r"""
    CommandLine:
        python -m wbia_whaleridgefindr._plugin --allexamples
    """
    import multiprocessing

    multiprocessing.freeze_support()  # for win32
    import utool as ut  # NOQA

    ut.doctest_funcs()
