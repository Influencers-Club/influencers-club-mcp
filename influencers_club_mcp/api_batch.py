"""Batch enrichment endpoints of the Influencers.club API. Reached as ``client.batch``.
Methods return the API's JSON body unchanged."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

from .api_paths import ROOT, segment

if TYPE_CHECKING:
    from .api_client import InfluencersApiClient

BATCH = f"{ROOT}/enrichment/batch/"
RESULTS_TIMEOUT = 120.0  # a finished batch can be large


def _batch_path(batch_id: str) -> str:
    """Route of one batch job."""
    return f"{BATCH}{segment(batch_id, 'batch_id')}/"


class BatchApi:
    """Batch operations, sent through the client that owns this object."""

    def __init__(self, client: InfluencersApiClient) -> None:
        self._client = client

    async def create(
        self,
        csv_bytes: bytes,
        enrichment_mode: str,
        *,
        platform: Optional[str] = None,
        email_required: Optional[str] = None,
        include_lookalikes: Optional[bool] = None,
        include_audience_data: Optional[bool] = None,
        metadata: Any = None,
    ) -> Any:
        """POST /enrichment/batch/ (multipart) - start a batch job from a CSV of handles or emails."""
        files = {"file": ("batch.csv", csv_bytes, "text/csv")}
        fields: dict[str, str] = {"enrichment_mode": enrichment_mode}
        if platform:
            fields["platform"] = platform
        if email_required:
            fields["email_required"] = email_required
        if include_lookalikes is not None:
            fields["include_lookalikes"] = str(include_lookalikes).lower()
        if include_audience_data is not None:
            fields["include_audience_data"] = str(include_audience_data).lower()
        if metadata:
            fields["metadata"] = json.dumps(metadata) if isinstance(metadata, dict) else str(metadata)
        return await self._client.post_multipart(BATCH, files, fields)

    async def status(self, batch_id: str) -> Any:
        """GET /enrichment/batch/{id}/status/ - progress of one job."""
        return await self._client.get(_batch_path(batch_id) + "status/")

    async def results(self, batch_id: str) -> Any:
        """GET /enrichment/batch/{id}/?format=json - the finished job's rows (the CSV format answers 404)."""
        return await self._client.get(_batch_path(batch_id), {"format": "json"}, timeout=RESULTS_TIMEOUT)

    async def resume(self, batch_id: str) -> Any:
        """POST /enrichment/batch/{id}/resume/ - continue a job paused for lack of credits."""
        return await self._client.post(_batch_path(batch_id) + "resume/", {})
