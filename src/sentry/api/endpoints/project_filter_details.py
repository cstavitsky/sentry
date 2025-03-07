from collections.abc import Iterable

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from sentry import audit_log
from sentry.api.base import region_silo_endpoint
from sentry.api.bases.project import ProjectEndpoint
from sentry.api.exceptions import ResourceDoesNotExist
from sentry.apidocs.constants import (
    RESPONSE_BAD_REQUEST,
    RESPONSE_FORBIDDEN,
    RESPONSE_NO_CONTENT,
    RESPONSE_NOT_FOUND,
)
from sentry.apidocs.parameters import GlobalParams, ProjectParams
from sentry.ingest import inbound_filters


@extend_schema(tags=["Projects"])
@region_silo_endpoint
class ProjectFilterDetailsEndpoint(ProjectEndpoint):
    public = {"PUT"}

    @extend_schema(
        operation_id="Update an Inbound Data Filter",
        parameters=[
            GlobalParams.ORG_SLUG,
            GlobalParams.PROJECT_SLUG,
            ProjectParams.FILTER_ID,
            ProjectParams.ACTIVE,
            ProjectParams.SUB_FILTERS,
        ],
        request=inline_serializer(
            name="FilterPutSerializer",
            fields={
                "active": serializers.CharField(required=False),
                "subfilters": serializers.ListField(child=serializers.CharField(required=False)),
            },
        ),
        responses={
            201: RESPONSE_NO_CONTENT,
            400: RESPONSE_BAD_REQUEST,
            403: RESPONSE_FORBIDDEN,
            404: RESPONSE_NOT_FOUND,
        },
        examples=None,
    )
    def put(self, request: Request, project, filter_id) -> Response:
        """
        Update various inbound data filters for a project.
        """
        current_filter = None
        for flt in inbound_filters.get_all_filter_specs():
            if flt.id == filter_id:
                current_filter = flt
                break
        else:
            raise ResourceDoesNotExist  # could not find filter with the requested id

        serializer = current_filter.serializer_cls(data=request.data, partial=True)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        current_state = inbound_filters.get_filter_state(filter_id, project)
        if isinstance(current_state, list):
            current_state = set(current_state)

        new_state = inbound_filters.set_filter_state(filter_id, project, serializer.validated_data)
        if isinstance(new_state, list):
            new_state = set(new_state)
        audit_log_state = audit_log.get_event_id("PROJECT_ENABLE")

        returned_state = None
        if filter_id == "legacy-browsers":
            if isinstance(current_state, bool) or isinstance(new_state, bool):
                returned_state = new_state
                if not new_state:
                    audit_log_state = audit_log.get_event_id("PROJECT_DISABLE")

            elif current_state - new_state:
                returned_state = current_state - new_state
                audit_log_state = audit_log.get_event_id("PROJECT_DISABLE")

            elif new_state - current_state:
                returned_state = new_state - current_state

            elif new_state == current_state:
                returned_state = new_state

        if filter_id in ("browser-extensions", "localhost", "web-crawlers"):
            returned_state = filter_id
            removed = current_state - new_state

            if removed == 1:
                audit_log_state = audit_log.get_event_id("PROJECT_DISABLE")

        if isinstance(returned_state, Iterable):
            returned_state = list(returned_state)
        self.create_audit_entry(
            request=request,
            organization=project.organization,
            target_object=project.id,
            event=audit_log_state,
            data={"state": returned_state},
        )

        return Response(status=201)
