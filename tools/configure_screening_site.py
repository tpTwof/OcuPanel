"""Provision a synthetic rehearsal site using existing local accounts."""
import argparse
import json
from pathlib import Path
import sys
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from pydantic import Field
from modules.screening.models import Contract, Text
from core import storage


class Site(Contract):
    organization: Text
    receiving_unit: Text
    emergency_contact: Text
    daily_capacity: int = Field(gt=0)
    members: dict[Text, Literal["capture", "reader", "coordinator"]]
    allowed_llm_endpoints: list[Text] = Field(default_factory=list)
    analysis_paused: bool = False


def configure(site: Site) -> None:
    with storage.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO screening_sites VALUES(?,?,?,?) ON CONFLICT(organization) DO UPDATE SET "
                     "receiving_unit=excluded.receiving_unit, emergency_contact=excluded.emergency_contact, "
                     "daily_capacity=excluded.daily_capacity",
                     (site.organization, site.receiving_unit, site.emergency_contact, site.daily_capacity))
        conn.execute("DELETE FROM screening_members WHERE organization=?", (site.organization,))
        conn.execute("INSERT INTO screening_site_policy VALUES(?,?,?) ON CONFLICT(organization) DO UPDATE SET "
                     "endpoints=excluded.endpoints, paused=excluded.paused",
                     (site.organization, json.dumps([url.rstrip('/') for url in site.allowed_llm_endpoints]), site.analysis_paused))
        for username, role in site.members.items():
            user = conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
            if user is None:
                raise ValueError(f"Unknown username: {username}")
            conn.execute("INSERT INTO screening_members VALUES(?,?,?)", (user["id"], site.organization, role))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path, help="Authoritative site roster in JSON")
    args = parser.parse_args()
    site = Site.model_validate(json.loads(args.file.read_text(encoding="utf8")))
    storage.init_db()
    configure(site)
