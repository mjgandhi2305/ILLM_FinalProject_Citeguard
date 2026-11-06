"""doi.org: registration check (any registration agency) and content negotiation."""

from __future__ import annotations

from urllib.parse import quote

from citeguard.domain.models import LookupStatus
from citeguard.sources.base import IdKind, SearchQuery, Source, SourceResponse, response
from citeguard.sources.csl import csl_to_record

CSL_JSON = "application/vnd.citationstyles.csl+json"


def _quote_doi(doi: str) -> str:
    return quote(doi, safe="/()._-:;")


class DoiOrg(Source):
    name = "doi"
    display_name = "doi.org"
    rate_per_s = 5.0
    lookup_kinds = frozenset({"doi"})
    can_search = False
    tier = "registry"

    async def registered(self, doi: str) -> SourceResponse:
        """Is this DOI registered with *any* agency (Crossref, DataCite, mEDRA, JaLC…)?"""
        url = f"https://doi.org/api/handles/{_quote_doi(doi)}"
        res = await self.http.get(url)
        browse = f"https://doi.org/{doi}"
        if res.ok and isinstance(res.data, dict) and res.data.get("responseCode") == 1:
            target = next(
                (
                    v.get("data", {}).get("value")
                    for v in res.data.get("values", [])
                    if v.get("type") == "URL"
                ),
                None,
            )
            return SourceResponse(
                status=LookupStatus.FOUND,
                url=browse,
                latency_ms=res.latency_ms,
                cached=res.cached,
                note=f"resolves to {target}" if target else "registered",
            )
        if res.not_found or (isinstance(res.data, dict) and res.data.get("responseCode") == 100):
            return SourceResponse(
                status=LookupStatus.NOT_FOUND,
                url=browse,
                latency_ms=res.latency_ms,
                cached=res.cached,
                note="DOI is not registered with any DOI registration agency",
            )
        return response(res, [], browse)

    async def lookup(self, kind: IdKind, value: str) -> SourceResponse:
        if kind != "doi":
            return await super().lookup(kind, value)
        url = f"https://doi.org/{_quote_doi(value)}"
        res = await self.http.get(url, headers={"Accept": CSL_JSON})
        records = []
        if res.ok and isinstance(res.data, dict):
            records = [csl_to_record(res.data, source=self.name, url=url)]
        return response(res, records, url)

    async def formatted(self, doi: str, style: str) -> str | None:
        """Formatted citation in any CSL style via content negotiation (Crossref/DataCite)."""
        url = f"https://doi.org/{_quote_doi(doi)}"
        accept = (
            f"text/x-bibliography; style={style}" if style != "bibtex" else "application/x-bibtex"
        )
        res = await self.http.get(url, headers={"Accept": accept}, as_json=False)
        if res.ok and isinstance(res.data, str) and res.data.strip():
            return res.data.strip()
        return None

    async def search(self, query: SearchQuery, limit: int = 5) -> SourceResponse:
        return SourceResponse(status=LookupStatus.UNAVAILABLE, note="doi.org has no search")
