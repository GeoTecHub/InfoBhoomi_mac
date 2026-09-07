"""
Hand-curated InfoBhoomi component map.
======================================
Decision #7: this is a Python file, reviewable in code review, kept in
sync by hand. ``drift_check()`` reports any declared path that does not
exist on disk, so unsynchronised entries are visible at a glance.

Each entry pins ONE function_id (matching FunctionDefinition.id in
function_registry.py) to its frontend, backend and database sub-components.
This is what the Architect Agent consults when it decides which Investigator
to call and what files each Investigator should look at.

Path conventions (relative to PROJECT_ROOT, configurable via env):
  AGENT_FE_ROOT  default: infoBhoomi-frontedend-div2
  AGENT_BE_ROOT  default: InfoBhoomi_Backend_dev2
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from config import AGENT_BE_ROOT, AGENT_FE_ROOT, PROJECT_ROOT
from agent_center.function_registry import all_functions


FrontendKind = Literal["component", "service", "guard", "directive", "module", "shared"]
BackendKind  = Literal["view", "serializer", "model", "url", "signal", "permission", "command"]


@dataclass(frozen=True)
class FrontendSubcomponent:
    path: str
    kind: FrontendKind
    responsibility: str


@dataclass(frozen=True)
class BackendSubcomponent:
    path: str
    kind: BackendKind
    responsibility: str


@dataclass(frozen=True)
class DBSubcomponent:
    table: str
    model: str
    key_fields: tuple[str, ...] = ()
    related_tables: tuple[str, ...] = ()


@dataclass(frozen=True)
class ComponentMapEntry:
    function_id: str
    frontend: tuple[FrontendSubcomponent, ...] = ()
    backend: tuple[BackendSubcomponent, ...] = ()
    db: tuple[DBSubcomponent, ...] = ()
    runtime_dependencies: tuple[str, ...] = ()


# ── FE shorthand ─────────────────────────────────────────────────────────────
_FE = "infoBhoomi-frontedend-div2/src/app"
_BE = "InfoBhoomi_Backend_dev2/user"


def _fe(p: str) -> str:
    return f"{_FE}/{p.lstrip('/')}"


def _be(p: str) -> str:
    return f"{_BE}/{p.lstrip('/')}"


# ── The map ───────────────────────────────────────────────────────────────────

COMPONENT_MAP: tuple[ComponentMapEntry, ...] = (
    ComponentMapEntry(
        function_id="auth.verify-session",
        frontend=(
            FrontendSubcomponent(_fe("components/auth/login-page"),     "component", "Login form"),
            FrontendSubcomponent(_fe("components/auth/guards"),         "guard",     "Route + permission guards"),
            FrontendSubcomponent(_fe("services/auth.service.ts"),       "service",   "Token storage + login API"),
            FrontendSubcomponent(_fe("services/login.service.ts"),      "service",   "Credential exchange"),
        ),
        backend=(
            BackendSubcomponent(_be("views/auth.py"),       "view",       "/login/, /verify-token/, /me/"),
            BackendSubcomponent(_be("serializers/auth.py"), "serializer", "Token + user serializers"),
            BackendSubcomponent(_be("models/auth.py"),      "model",      "UserAccount, Token"),
            BackendSubcomponent(_be("urls.py"),             "url",        "/api/user/* routing"),
        ),
        db=(
            DBSubcomponent("authtoken_token",     "Token",       ("key", "user_id")),
            DBSubcomponent("user_useraccounts",   "UserAccount", ("id", "username")),
        ),
    ),
    ComponentMapEntry(
        function_id="users.admin",
        frontend=(
            FrontendSubcomponent(_fe("admin/user/users-list"),   "component", "List users"),
            FrontendSubcomponent(_fe("admin/user/users-create"), "component", "Create user"),
            FrontendSubcomponent(_fe("admin/user/user-edit"),    "component", "Edit user"),
            FrontendSubcomponent(_fe("services/user.service.ts"),"service",   "User admin API"),
            FrontendSubcomponent(_fe("services/admin.service.ts"),"service",  "Admin-side operations"),
        ),
        backend=(
            BackendSubcomponent(_be("views/users.py"),       "view",       "User CRUD"),
            BackendSubcomponent(_be("serializers/auth.py"),  "serializer", "User serializers"),
            BackendSubcomponent(_be("models/auth.py"),       "model",      "UserAccount"),
        ),
        db=(
            DBSubcomponent("user_useraccounts", "UserAccount", ("id", "username")),
        ),
        runtime_dependencies=("auth.verify-session", "roles.permissions"),
    ),
    ComponentMapEntry(
        function_id="organizations.admin",
        frontend=(
            FrontendSubcomponent(_fe("admin/organizations/organizations-list"),         "component", "Org list"),
            FrontendSubcomponent(_fe("admin/organizations/organizations-create"),       "component", "Create org"),
            FrontendSubcomponent(_fe("admin/organizations/organization-edit"),          "component", "Edit org"),
            FrontendSubcomponent(_fe("admin/organizations/organization-area-edit"),     "component", "Edit org boundary"),
            FrontendSubcomponent(_fe("admin/organizations/organizations-location-edit"),"component", "Edit map start point"),
            FrontendSubcomponent(_fe("services/org-area-define.service.ts"),            "service",   "Boundary editor logic"),
        ),
        backend=(
            BackendSubcomponent(_be("views/organization.py"),       "view",       "/sl-orgnization/, /org_*"),
            BackendSubcomponent(_be("serializers/organization.py"), "serializer", "Org serializers"),
            BackendSubcomponent(_be("models/organization.py"),      "model",      "SL_Organization, SL_Org_Area"),
        ),
        db=(
            DBSubcomponent("user_sl_organization", "SL_Organization", ("id",)),
            DBSubcomponent("user_sl_org_area",     "SL_Org_Area",     ("organization_id",)),
        ),
        runtime_dependencies=("auth.verify-session",),
    ),
    ComponentMapEntry(
        function_id="roles.permissions",
        frontend=(
            FrontendSubcomponent(_fe("admin/roles-list"),                                  "component", "Roles admin"),
            FrontendSubcomponent(_fe("components/auth/guards"),                            "guard",     "permission-check guards"),
            FrontendSubcomponent(_fe("services/permissions.service.ts"),                   "service",   "Permission cache + checks"),
            FrontendSubcomponent(_fe("components/dialogs/add-role"),                       "component", "Add role dialog"),
            FrontendSubcomponent(_fe("components/dialogs/add-role-users"),                 "component", "Add users to role"),
        ),
        backend=(
            BackendSubcomponent(_be("views/roles.py"),       "view",       "Role + permission endpoints"),
            BackendSubcomponent(_be("serializers/roles.py"), "serializer", "Role serializers"),
            BackendSubcomponent(_be("models/auth.py"),       "model",      "UserRoles, RolePermission"),
        ),
        db=(
            DBSubcomponent("user_user_roles",      "UserRoles",      ("id",)),
            DBSubcomponent("user_role_permission", "RolePermission", ("role_id", "permission_id")),
        ),
        runtime_dependencies=("auth.verify-session",),
    ),
    ComponentMapEntry(
        function_id="layers.management",
        frontend=(
            FrontendSubcomponent(_fe("components/layer-panel"),       "component", "Layer panel UI"),
            FrontendSubcomponent(_fe("admin/layers-list"),            "component", "Admin layer list"),
            FrontendSubcomponent(_fe("services/layer.service.ts"),    "service",   "Layer CRUD + visibility"),
            FrontendSubcomponent(_fe("services/style-factory.service.ts"), "service", "Layer styling"),
            FrontendSubcomponent(_fe("components/dialogs/add-layer"), "component", "Add-layer dialog"),
            FrontendSubcomponent(_fe("components/dialogs/share-layer"),"component", "Share-layer dialog"),
        ),
        backend=(
            BackendSubcomponent(_be("views/layers.py"),       "view",       "/layerdata_get_*"),
            BackendSubcomponent(_be("serializers/layers.py"), "serializer", "Layer serializers"),
            BackendSubcomponent(_be("models/core.py"),        "model",      "Layer_Data"),
        ),
        db=(
            DBSubcomponent("user_layer_data", "Layer_Data", ("layer_id",)),
        ),
        runtime_dependencies=("auth.verify-session", "roles.permissions"),
    ),
    ComponentMapEntry(
        function_id="map.workspace",
        frontend=(
            FrontendSubcomponent(_fe("components/main"),                 "component", "Main map workspace"),
            FrontendSubcomponent(_fe("services/map.service.ts"),         "service",   "OpenLayers map facade"),
            FrontendSubcomponent(_fe("services/app-state.service.ts"),   "service",   "Cross-component state"),
            FrontendSubcomponent(_fe("services/sidebar-control.service.ts"), "service", "Side-panel routing"),
            FrontendSubcomponent(_fe("services/toolbar-action.service.ts"),  "service", "Toolbar dispatch"),
        ),
        backend=(
            BackendSubcomponent(_be("views/organization.py"), "view", "Boundary + start location"),
            BackendSubcomponent(_be("views/layers.py"),       "view", "Map layer payload"),
        ),
        db=(
            DBSubcomponent("user_sl_org_area", "SL_Org_Area", ("organization_id",)),
            DBSubcomponent("user_layer_data",  "Layer_Data",  ("layer_id",)),
        ),
        runtime_dependencies=("auth.verify-session", "organizations.admin", "layers.management"),
    ),
    ComponentMapEntry(
        function_id="survey.geometry",
        frontend=(
            FrontendSubcomponent(_fe("services/draw.service.ts"),    "service", "OpenLayers draw orchestration"),
            FrontendSubcomponent(_fe("services/geom.service.ts"),    "service", "Geometry helpers"),
            FrontendSubcomponent(_fe("services/feature.service.ts"), "service", "Feature CRUD against API"),
            FrontendSubcomponent(_fe("services/feature-link.service.ts"), "service", "Cross-feature linking"),
            FrontendSubcomponent(_fe("services/split.service.ts"),   "service", "Polygon split workflow"),
            FrontendSubcomponent(_fe("services/vertext.service.ts"), "service", "Vertex editing"),
        ),
        backend=(
            BackendSubcomponent(_be("views/survey.py"),         "view",       "/survey_rep_data*"),
            BackendSubcomponent(_be("views/spatial_units.py"),  "view",       "Spatial unit lifecycle"),
            BackendSubcomponent(_be("views/geo_utils.py"),      "view",       "Geometry utilities"),
            BackendSubcomponent(_be("serializers/survey.py"),   "serializer", "Survey rep serializers"),
            BackendSubcomponent(_be("serializers/spatial_units.py"), "serializer", "Spatial unit serializers"),
            BackendSubcomponent(_be("models/spatial_units.py"), "model",      "LA_Spatial_Unit_Model, survey_rep"),
            BackendSubcomponent(_be("models/geo.py"),           "model",      "Geometry-bearing models"),
        ),
        db=(
            DBSubcomponent("la_spatial_unit_model", "LA_Spatial_Unit_Model", ("su_id",)),
            DBSubcomponent("survey_rep",            "survey_rep",            ("su_id",), ("la_spatial_unit_model",)),
        ),
        runtime_dependencies=("auth.verify-session", "layers.management", "map.workspace"),
    ),
    ComponentMapEntry(
        function_id="land.attributes",
        frontend=(
            FrontendSubcomponent(_fe("components/side-panel/land-info-panel"),  "component", "Land attribute side panel"),
            FrontendSubcomponent(_fe("components/dialogs/land-parcel-report"),  "component", "Land parcel report dialog"),
        ),
        backend=(
            BackendSubcomponent(_be("views/land.py"),            "view",       "/lnd-* endpoints"),
            BackendSubcomponent(_be("models/spatial_units.py"),  "model",      "Lnd_Admin_Info, Lnd_Overview"),
            BackendSubcomponent(_be("models/assessments.py"),    "model",      "Tax_Assessment"),
        ),
        db=(
            DBSubcomponent("lnd_admin_info", "Lnd_Admin_Info", ("su_id",)),
            DBSubcomponent("lnd_overview",   "Lnd_Overview",   ("su_id",)),
            DBSubcomponent("tax_assessment", "Tax_Assessment", ("su_id",)),
        ),
        runtime_dependencies=("survey.geometry",),
    ),
    ComponentMapEntry(
        function_id="building.attributes",
        frontend=(
            FrontendSubcomponent(_fe("components/side-panel/building-info-panel"),       "component", "Building side panel"),
            FrontendSubcomponent(_fe("components/dialogs/building-report"),              "component", "Building report dialog"),
            FrontendSubcomponent(_fe("components/dialogs/three-d-building-viewer"),     "component", "3D building viewer"),
        ),
        backend=(
            BackendSubcomponent(_be("views/building.py"),       "view",  "/bld-* endpoints"),
            BackendSubcomponent(_be("models/spatial_units.py"), "model", "Bld_Admin_Info, Bld_Unit"),
        ),
        db=(
            DBSubcomponent("bld_admin_info", "Bld_Admin_Info", ("su_id",)),
            DBSubcomponent("survey_rep",     "Bld_Unit",       ("su_id",)),
        ),
        runtime_dependencies=("survey.geometry",),
    ),
    ComponentMapEntry(
        function_id="rrr.lifecycle",
        frontend=(
            FrontendSubcomponent(_fe("components/dialogs/add-right-holder"), "component", "Add right holder dialog"),
            FrontendSubcomponent(_fe("components/dialogs/rrr-panal"),         "component", "RRR side panel"),
            FrontendSubcomponent(_fe("components/dialogs/generate-report"),  "component", "RRR report"),
        ),
        backend=(
            BackendSubcomponent(_be("views/rrr.py"),       "view",       "/rrr_* endpoints"),
            BackendSubcomponent(_be("serializers/rrr.py"), "serializer", "RRR serializers"),
            BackendSubcomponent(_be("models/rrr.py"),      "model",      "BA Unit, RRR, RRR_Audit"),
        ),
        db=(
            DBSubcomponent("sl_ba_unit_model",   "SL_BA_Unit_Model", ("su_id",)),
            DBSubcomponent("rrr",                "RRR",              ("ba_unit_id",), ("sl_ba_unit_model",)),
            DBSubcomponent("rrr_audit_history",  "RRR_Audit",        ("su_id",)),
        ),
        runtime_dependencies=("survey.geometry", "party.right-holders"),
    ),
    ComponentMapEntry(
        function_id="party.right-holders",
        frontend=(
            FrontendSubcomponent(_fe("components/dialogs/civilian"),    "component", "Civilian party form"),
            FrontendSubcomponent(_fe("components/dialogs/company"),     "component", "Company party form"),
            FrontendSubcomponent(_fe("components/dialogs/group"),       "component", "Group party form"),
            FrontendSubcomponent(_fe("components/dialogs/legal-firm"),  "component", "Legal firm party form"),
        ),
        backend=(
            BackendSubcomponent(_be("views/party.py"),       "view",       "/sl-party*"),
            BackendSubcomponent(_be("serializers/party.py"), "serializer", "Party serializers"),
            BackendSubcomponent(_be("models/party.py"),      "model",      "SL_Party"),
        ),
        db=(
            DBSubcomponent("sl_party", "SL_Party", ("pid",)),
        ),
    ),
    ComponentMapEntry(
        function_id="query.export",
        frontend=(
            FrontendSubcomponent(_fe("components/dialogs/gis-query-console"),  "component", "GIS query console"),
            FrontendSubcomponent(_fe("components/shared/popups"),              "component", "Query builder popup"),
        ),
        backend=(
            BackendSubcomponent(_be("views/search.py"),         "view",       "/search/, /query-parcels/"),
            BackendSubcomponent(_be("serializers/spatial_units.py"), "serializer", "Result serializers"),
        ),
        db=(
            DBSubcomponent("survey_rep", "survey_rep", ("su_id",)),
        ),
        runtime_dependencies=("survey.geometry",),
    ),
    ComponentMapEntry(
        function_id="documents.media",
        frontend=(
            FrontendSubcomponent(_fe("components/shared/popups"),  "component", "Import-data popup"),
            FrontendSubcomponent(_fe("components/shared/panel-img"),"component", "Image panel"),
        ),
        backend=(
            BackendSubcomponent(_be("views/spatial_units.py"), "view",  "Media + admin source endpoints"),
            BackendSubcomponent(_be("models/media.py"),        "model", "Attrib_Image, LA_Spatial_Source"),
        ),
        db=(
            DBSubcomponent("la_spatial_source", "LA_Spatial_Source", ("su_id",)),
            DBSubcomponent("attrib_image",      "Attrib_Image",      ("su_id",)),
        ),
        runtime_dependencies=("survey.geometry",),
    ),
    ComponentMapEntry(
        function_id="dynamic.attributes",
        frontend=(
            FrontendSubcomponent(_fe("components/shared/key-value"),         "shared", "Key-value editor"),
            FrontendSubcomponent(_fe("components/shared/key-value-dropdown"),"shared", "Key-value dropdown"),
            FrontendSubcomponent(_fe("components/shared/key-value-v2"),      "shared", "Key-value v2 editor"),
        ),
        backend=(
            BackendSubcomponent(_be("views/dynamic.py"),       "view",       "/dynamic-attribute*"),
            BackendSubcomponent(_be("serializers/dynamic.py"), "serializer", "Dynamic attribute serializers"),
            BackendSubcomponent(_be("models/misc.py"),         "model",      "DynamicAttribute"),
        ),
        db=(
            DBSubcomponent("dynamic_attribute", "DynamicAttribute", ("id",)),
        ),
    ),
    ComponentMapEntry(
        function_id="history.audit",
        frontend=(
            FrontendSubcomponent(_fe("components/side-panel"), "component", "Side panels with audit views"),
        ),
        backend=(
            BackendSubcomponent(_be("views/spatial_units.py"), "view",  "History endpoints"),
            BackendSubcomponent(_be("models/history.py"),      "model", "SurveyRepHistory, History_Spartialunit_Attrib"),
        ),
        db=(
            DBSubcomponent("survey_rep_history",          "SurveyRepHistory",            ("su_id",)),
            DBSubcomponent("history_spartialunit_attrib", "History_Spartialunit_Attrib", ("su_id",)),
        ),
        runtime_dependencies=("survey.geometry", "rrr.lifecycle"),
    ),
    ComponentMapEntry(
        function_id="lookups.reference",
        frontend=(
            FrontendSubcomponent(_fe("services/data.service.ts"), "service", "Lookup data cache"),
        ),
        backend=(
            BackendSubcomponent(_be("views/lookups.py"),       "view",       "/lst-* endpoints"),
            BackendSubcomponent(_be("serializers/lookups.py"), "serializer", "Lookup serializers"),
            BackendSubcomponent(_be("models/lookups.py"),      "model",      "Lookup tables"),
        ),
        db=(
            DBSubcomponent("lst_*", "Lookup tables", ()),
        ),
    ),
    ComponentMapEntry(
        function_id="communication.workflow",
        frontend=(
            FrontendSubcomponent(_fe("components/dialogs/admin-contact"), "component", "Contact dialog"),
            FrontendSubcomponent(_fe("components/dialogs/online-users"),  "component", "Online users dialog"),
            FrontendSubcomponent(_fe("services/notifications.service.ts"),"service",   "Toast / notify"),
            FrontendSubcomponent(_fe("services/activity-log.service.ts"), "service",   "Activity logging"),
        ),
        backend=(
            BackendSubcomponent(_be("views/spatial_units.py"), "view", "Messages/inquiries/reminders endpoints"),
            BackendSubcomponent(_be("models/misc.py"),         "model","Messages, Inquiries, Reminders, Tags"),
        ),
        db=(
            DBSubcomponent("messages",   "Messages",   ()),
            DBSubcomponent("inquiries",  "Inquiries",  ()),
            DBSubcomponent("reminders",  "Reminders",  ()),
            DBSubcomponent("tags",       "Tags",       ()),
        ),
    ),
)


# ── Lookup helpers ────────────────────────────────────────────────────────────

def all_entries() -> list[ComponentMapEntry]:
    return list(COMPONENT_MAP)


def get_entry(function_id: str) -> ComponentMapEntry:
    for entry in COMPONENT_MAP:
        if entry.function_id == function_id:
            return entry
    raise KeyError(f"No component map entry for function_id '{function_id}'")


def function_ids() -> list[str]:
    return [entry.function_id for entry in COMPONENT_MAP]


# ── Drift checker ─────────────────────────────────────────────────────────────

def drift_check() -> dict:
    """
    Verify every declared FE/BE path exists on disk under PROJECT_ROOT.
    Returns a dict suitable for printing or unit-test consumption.
    """
    missing_fe: list[str] = []
    missing_be: list[str] = []
    for entry in COMPONENT_MAP:
        for sc in entry.frontend:
            if not (PROJECT_ROOT / sc.path).exists():
                missing_fe.append(sc.path)
        for sc in entry.backend:
            if not (PROJECT_ROOT / sc.path).exists():
                missing_be.append(sc.path)
    return {
        "fe_root": str(AGENT_FE_ROOT),
        "be_root": str(AGENT_BE_ROOT),
        "missing_fe_paths": missing_fe,
        "missing_be_paths": missing_be,
        "ok": not missing_fe and not missing_be,
    }


def coverage_check() -> dict:
    """Confirm every function_id in function_registry has a map entry."""
    registry_ids = {fn.id for fn in all_functions()}
    map_ids      = set(function_ids())
    return {
        "registry_only": sorted(registry_ids - map_ids),
        "map_only":      sorted(map_ids - registry_ids),
        "both":          sorted(registry_ids & map_ids),
        "ok":            registry_ids == map_ids,
    }


if __name__ == "__main__":
    import json
    print(json.dumps({"drift": drift_check(), "coverage": coverage_check()}, indent=2))
