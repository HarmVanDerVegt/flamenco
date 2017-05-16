import functools
import logging

import bson
from flask import Blueprint, render_template, redirect, url_for

from pillar.web.utils import attach_project_pictures
from pillar.web.system_util import pillar_api
import pillarsdk

from flamenco import current_flamenco


blueprint = Blueprint('flamenco', __name__)
log = logging.getLogger(__name__)


@blueprint.route('/')
def index():
    api = pillar_api()

    # FIXME Sybren: add permission check.
    # TODO: add projections.
    projects = current_flamenco.flamenco_projects()

    for project in projects['_items']:
        attach_project_pictures(project, api)

    projs_with_summaries = [
        (proj, current_flamenco.job_manager.job_status_summary(proj['_id']))
        for proj in projects['_items']
        ]

    return render_template('flamenco/index.html',
                           projs_with_summaries=projs_with_summaries)


def error_project_not_setup_for_flamenco():
    return render_template('flamenco/errors/project_not_setup.html')


def error_project_not_available():
    import flask

    if flask.request.is_xhr:
        resp = flask.jsonify({'_error': 'project not available on Flamenco'})
        resp.status_code = 403
        return resp

    return render_template('flamenco/errors/project_not_available.html')


def flamenco_project_view(extra_project_projections: dict=None,
                          *,
                          extension_props=False,
                          require_usage_rights=True):
    """Decorator, replaces the first parameter project_url with the actual project.

    Assumes the first parameter to the decorated function is 'project_url'. It then
    looks up that project, checks that it's set up for Flamenco, and passes it to the
    decorated function.

    If not set up for flamenco, uses error_project_not_setup_for_flamenco() to render
    the response.

    :param extra_project_projections: extra projections to use on top of the ones already
        used by this decorator.
    :param extension_props: when True, passes (project, extension_props) as first parameters
        to the decorated function. When False, just passes (project, ).
    :param require_usage_rights: when True, requires that a Flamenco Manager is assigned
        to the project, and that the user has access to this manager (i.e. is part of this
        project).
    """

    import flask_login

    from . import EXTENSION_NAME

    if callable(extra_project_projections):
        raise TypeError('Use with @flamenco_project_view() <-- note the parentheses')

    projections = {
        '_id': 1,
        'name': 1,
        'permissions': 1,
        'extension_props.%s' % EXTENSION_NAME: 1,
        # We don't need this here, but this way the wrapped function has access
        # to the orignal URL passed to it.
        'url': 1,
    }
    if extra_project_projections:
        projections.update(extra_project_projections)

    def decorator(wrapped):
        @functools.wraps(wrapped)
        def wrapper(project_url, *args, **kwargs):
            if isinstance(project_url, pillarsdk.Resource):
                # This is already a resource, so this call probably is from one
                # view to another. Assume the caller knows what he's doing and
                # just pass everything along.
                return wrapped(project_url, *args, **kwargs)

            api = pillar_api()

            project = pillarsdk.Project.find_by_url(
                project_url,
                {'projection': projections},
                api=api)

            is_flamenco = current_flamenco.is_flamenco_project(project)
            if not is_flamenco:
                return error_project_not_setup_for_flamenco()

            if require_usage_rights:
                project_id = bson.ObjectId(project['_id'])
                if not current_flamenco.auth.current_user_may_use_project(project_id):
                    log.info('Denying user %s access to Flamenco on project %s',
                             flask_login.current_user, project_id)
                    return error_project_not_available()

            if extension_props:
                pprops = project.extension_props.flamenco
                return wrapped(project, pprops, *args, **kwargs)
            return wrapped(project, *args, **kwargs)

        return wrapper

    return decorator


@blueprint.route('/<project_url>')
@flamenco_project_view(extension_props=False)
def project_index(project):
    return redirect(url_for('flamenco.jobs.perproject.index', project_url=project.url))


@blueprint.route('/<project_url>/help')
@flamenco_project_view(extension_props=False)
def help(project):
    return render_template('flamenco/help.html', statuses=[])
