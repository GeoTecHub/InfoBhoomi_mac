from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


VerificationMode = Literal["api", "db", "api+db"]
Severity = Literal["critical", "high", "medium", "low"]
HttpMethod = Literal["GET", "POST", "PATCH", "DELETE"]


@dataclass(frozen=True)
class EndpointCheck:
    method: HttpMethod
    path: str
    purpose: str
    body: dict | None = None
    destructive: bool = False


@dataclass(frozen=True)
class DbCheck:
    model: str
    table: str
    key_fields: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""


@dataclass(frozen=True)
class FunctionDefinition:
    id: str
    display_name: str
    category: str
    subcategory: str
    frontend: str
    endpoints: tuple[EndpointCheck, ...]
    db_checks: tuple[DbCheck, ...]
    required_test_data: tuple[str, ...]
    verification: VerificationMode
    cleanup: str
    severity: Severity
    keywords: tuple[str, ...]
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


FUNCTIONS: tuple[FunctionDefinition, ...] = (
    FunctionDefinition(
        id="auth.verify-session",
        display_name="Login and token verification",
        category="Auth",
        subcategory="Session access",
        frontend="components/auth/login-page, components/auth/guards",
        endpoints=(
            EndpointCheck("GET", "/verify-token/", "Verify current DRF token"),
            EndpointCheck("GET", "/me/", "Fetch current user profile"),
        ),
        db_checks=(DbCheck("Token/UserAccount", "authtoken_token,user_useraccounts"),),
        required_test_data=("Valid IB_TOKEN or IB_USERNAME/IB_PASSWORD",),
        verification="api+db",
        cleanup="None",
        severity="critical",
        keywords=("login", "auth", "token", "password", "session", "access"),
    ),
    FunctionDefinition(
        id="users.admin",
        display_name="User administration",
        category="Users",
        subcategory="Admin user management",
        frontend="admin/user/users-list, admin/user/users-create, admin/user/user-edit",
        endpoints=(
            EndpointCheck("GET", "/list/", "List users for admin panel"),
            EndpointCheck("GET", "/list-add-user-roles/", "List users for role assignment"),
            EndpointCheck("GET", "/user_overview/", "Load user overview"),
        ),
        db_checks=(DbCheck("UserAccounts", "user_useraccounts"),),
        required_test_data=("Authenticated admin user",),
        verification="api+db",
        cleanup="None for read-only checks",
        severity="high",
        keywords=("user", "users", "account", "online", "admin user"),
    ),
    FunctionDefinition(
        id="organizations.admin",
        display_name="Organization setup and area",
        category="Organizations",
        subcategory="Organization details, area, location",
        frontend="admin/organizations/*",
        endpoints=(
            EndpointCheck("GET", "/sl-orgnization/", "List organizations"),
            EndpointCheck("GET", "/org_details/", "Current user's organization details"),
            EndpointCheck("GET", "/org_area/", "Current user's organization area"),
            EndpointCheck("GET", "/org_loc_get/", "Current user's map start location"),
        ),
        db_checks=(DbCheck("SL_Organization/OrgArea", "user_sl_organization,user_sl_org_area"),),
        required_test_data=("Authenticated admin or super admin user",),
        verification="api+db",
        cleanup="None for read-only checks",
        severity="high",
        keywords=("organization", "org", "boundary", "area", "location", "gnd"),
    ),
    FunctionDefinition(
        id="roles.permissions",
        display_name="Roles and permissions",
        category="Roles",
        subcategory="Role permission control",
        frontend="admin/roles-list, components/auth/guards/permission-check.guard",
        endpoints=(
            EndpointCheck("GET", "/user-roles-get-admin/", "List admin roles"),
            EndpointCheck("GET", "/role-permission-layerpanel/", "Layer panel permissions"),
        ),
        db_checks=(DbCheck("UserRoles/RolePermission", "user_user_roles,user_role_permission"),),
        required_test_data=("Authenticated admin user",),
        verification="api+db",
        cleanup="None for read-only checks",
        severity="critical",
        keywords=("role", "permission", "access", "guard", "layer permission"),
    ),
    FunctionDefinition(
        id="layers.management",
        display_name="Layer management",
        category="Layers",
        subcategory="Layer create/list/update/delete",
        frontend="components/layer-panel, admin/layers-list",
        endpoints=(
            EndpointCheck("GET", "/layerdata_get_user/", "Load user layers"),
            EndpointCheck("GET", "/layerdata_get_admin/", "Load admin layers"),
            EndpointCheck("GET", "/layerdata_get_admin_panel/", "Load admin control panel layers"),
        ),
        db_checks=(DbCheck("Layer_Data", "user_layer_data"),),
        required_test_data=("Authenticated user with layer access",),
        verification="api+db",
        cleanup="Generated layers must be deleted when destructive tests are enabled",
        severity="critical",
        keywords=("layer", "layers", "visibility", "style", "panel", "map layer"),
    ),
    FunctionDefinition(
        id="map.workspace",
        display_name="Main Web-GIS workspace",
        category="Map/GIS",
        subcategory="Map initialization and display",
        frontend="components/main, services/map.service, services/app-state.service",
        endpoints=(
            EndpointCheck("GET", "/org_area/", "Load organization boundary"),
            EndpointCheck("GET", "/org_loc_get/", "Load map initialization point"),
            EndpointCheck("GET", "/layerdata_get_user/", "Load map layers"),
        ),
        db_checks=(
            DbCheck("SL_Org_Area", "user_sl_org_area"),
            DbCheck("Layer_Data", "user_layer_data"),
        ),
        required_test_data=("Authenticated user",),
        verification="api+db",
        cleanup="None",
        severity="critical",
        keywords=("map", "workspace", "openlayers", "extent", "blank map", "base map"),
    ),
    FunctionDefinition(
        id="survey.geometry",
        display_name="Survey geometry save/retrieve/update",
        category="Survey Geometry",
        subcategory="Point, line, polygon lifecycle",
        frontend="services/draw.service, services/geom.service, services/feature.service",
        endpoints=(
            EndpointCheck("POST", "/survey_rep_data_user/", "Retrieve user spatial features", body={}),
            EndpointCheck("POST", "/survey_rep_data/", "Create test spatial feature", destructive=True),
            EndpointCheck("PATCH", "/survey_rep_data/update/id={id}/", "Update spatial feature", destructive=True),
            EndpointCheck("DELETE", "/survey_rep_data/bulk_delete/", "Cleanup test spatial feature", destructive=True),
        ),
        db_checks=(
            DbCheck("LA_Spatial_Unit_Model", "la_spatial_unit_model", ("su_id",)),
            DbCheck("survey_rep", "survey_rep", ("su_id",)),
        ),
        required_test_data=("Safe test layer", "GND id", "Tagged [AGENT-QA] geometry payload"),
        verification="api+db",
        cleanup="Bulk delete tagged [AGENT-QA] spatial units",
        severity="critical",
        keywords=("parcel", "geometry", "polygon", "point", "line", "draw", "save", "spatial"),
    ),
    FunctionDefinition(
        id="land.attributes",
        display_name="Land parcel attributes",
        category="Land",
        subcategory="Admin, overview, zoning, environment, utility, tax",
        frontend="components/side-panel/land-info-panel, dialogs/land-parcel-report",
        endpoints=(
            EndpointCheck("GET", "/lnd-admin-info/su_id={su_id}/", "Load land admin information"),
            EndpointCheck("GET", "/land-overview-info/su_id={su_id}/", "Load land overview"),
            EndpointCheck("GET", "/lnd-zoning-info/su_id={su_id}/", "Load zoning"),
            EndpointCheck("GET", "/lnd-physical-env/su_id={su_id}/", "Load physical environment"),
            EndpointCheck("GET", "/lnd-utinet-info/su_id={su_id}/", "Load utility network"),
            EndpointCheck("GET", "/tax-assess-info/su_id={su_id}/", "Load tax assessment"),
        ),
        db_checks=(
            DbCheck("Lnd_Admin_Info", "lnd_admin_info", ("su_id",)),
            DbCheck("Lnd_Overview", "lnd_overview", ("su_id",)),
            DbCheck("Tax_Assessment", "tax_assessment", ("su_id",)),
        ),
        required_test_data=("Existing land parcel su_id"),
        verification="api+db",
        cleanup="Attribute update tests must restore previous values",
        severity="critical",
        keywords=("land", "parcel", "admin info", "zoning", "tax", "utility", "assessment"),
    ),
    FunctionDefinition(
        id="building.attributes",
        display_name="Building and unit attributes",
        category="Building",
        subcategory="Building admin, overview, utility, unit management",
        frontend="components/side-panel/building-info-panel, dialogs/building-report",
        endpoints=(
            EndpointCheck("GET", "/bld-units/", "List building units"),
            EndpointCheck("GET", "/bld-admin-info/su_id={su_id}/", "Load building admin information"),
            EndpointCheck("GET", "/bld-overview-info/su_id={su_id}/", "Load building overview"),
            EndpointCheck("GET", "/bld-utinet-info/su_id={su_id}/", "Load building utility network"),
        ),
        db_checks=(
            DbCheck("Bld_Admin_Info", "bld_admin_info", ("su_id",)),
            DbCheck("Bld_Unit", "survey_rep", ("su_id",)),
        ),
        required_test_data=("Existing building su_id"),
        verification="api+db",
        cleanup="Created test units must be removed when destructive tests are enabled",
        severity="high",
        keywords=("building", "unit", "apartment", "floor", "utility"),
    ),
    FunctionDefinition(
        id="rrr.lifecycle",
        display_name="RRR lifecycle",
        category="RRR",
        subcategory="Rights, restrictions, responsibilities, BA Units",
        frontend="dialogs/add-right-holder, side panels, report dialogs",
        endpoints=(
            EndpointCheck("GET", "/rrr_data_get/?su_id={su_id}", "Load RRR records"),
            EndpointCheck("GET", "/ba-unit-id/su_id={su_id}/", "Load BA Unit id"),
            EndpointCheck("GET", "/rrr-history/?su_id={su_id}", "Load RRR audit history"),
            EndpointCheck("POST", "/rrr_data_save/", "Create RRR test record", destructive=True),
            EndpointCheck("PATCH", "/rrr/terminate/{rrr_id}/", "Terminate RRR record", destructive=True),
        ),
        db_checks=(
            DbCheck("SL_BA_Unit_Model", "sl_ba_unit_model", ("su_id",)),
            DbCheck("RRR", "rrr", ("ba_unit_id",)),
            DbCheck("RRR_Audit", "rrr_audit_history", ("su_id",)),
        ),
        required_test_data=("Existing spatial unit su_id", "Valid party PID"),
        verification="api+db",
        cleanup="Terminate or remove tagged [AGENT-QA] RRR records",
        severity="critical",
        keywords=("rrr", "right", "owner", "ownership", "ba unit", "restriction", "responsibility"),
    ),
    FunctionDefinition(
        id="party.right-holders",
        display_name="Parties and right holders",
        category="Parties",
        subcategory="Civilian, company, group, legal firm parties",
        frontend="dialogs/civilian, dialogs/company, dialogs/group, dialogs/legal-firm",
        endpoints=(
            EndpointCheck("GET", "/sl-party/", "List/create parties"),
            EndpointCheck("POST", "/sl-party-data/", "Search party by identity", body={}),
            EndpointCheck("POST", "/sl-party-data-pid/", "Search party by PID", body={}),
        ),
        db_checks=(DbCheck("SL_Party", "sl_party", ("pid",)),),
        required_test_data=("Existing party or tagged test party"),
        verification="api+db",
        cleanup="Tagged test parties should be removed or reused safely",
        severity="high",
        keywords=("party", "right holder", "owner", "civilian", "company", "legal", "group"),
    ),
    FunctionDefinition(
        id="query.export",
        display_name="Search, query builder, and export",
        category="Search/Query/Export",
        subcategory="Search geometry, query parcels, shapefile export",
        frontend="dialogs/gis-query-console, shared/popups/query-builder, export-data",
        endpoints=(
            EndpointCheck("POST", "/search/", "Run spatial/text search", body={}),
            EndpointCheck("POST", "/query-parcels/", "Run query builder", body={}),
            EndpointCheck("POST", "/query-parcels/export-shp/", "Export query result as shapefile", body={}),
        ),
        db_checks=(DbCheck("survey_rep/attributes", "survey_rep"),),
        required_test_data=("Queryable spatial features"),
        verification="api+db",
        cleanup="None for read-only query checks",
        severity="high",
        keywords=("query", "search", "export", "shapefile", "filter", "builder"),
    ),
    FunctionDefinition(
        id="documents.media",
        display_name="Documents, images, and spatial sources",
        category="Documents",
        subcategory="Attribute images, admin source PDFs, spatial sources",
        frontend="shared/popups/import-data, report dialogs, side panels",
        endpoints=(
            EndpointCheck("GET", "/la-spatial-source-retrive/su_id={su_id}/", "Retrieve spatial source"),
            EndpointCheck("GET", "/attrib-image-retrive/su_id={su_id}/", "Retrieve attribute images"),
            EndpointCheck("GET", "/admin-source/file/{admin_source_id}/", "Download admin source PDF"),
        ),
        db_checks=(
            DbCheck("LA_Spatial_Source", "la_spatial_source", ("su_id",)),
            DbCheck("Attrib_Image", "attrib_image", ("su_id",)),
        ),
        required_test_data=("Existing su_id or admin_source_id"),
        verification="api+db",
        cleanup="Uploaded test media must be deleted when destructive tests are enabled",
        severity="medium",
        keywords=("document", "pdf", "image", "source", "upload", "media"),
    ),
    FunctionDefinition(
        id="dynamic.attributes",
        display_name="Dynamic attributes",
        category="Dynamic Attributes",
        subcategory="Custom attribute definitions and values",
        frontend="shared/key-value, shared/key-value-dropdown, shared/key-value-v2",
        endpoints=(
            EndpointCheck("GET", "/dynamic-attribute/", "List dynamic attributes"),
            EndpointCheck("POST", "/dynamic-attribute-value/", "Save dynamic attribute value", destructive=True),
        ),
        db_checks=(DbCheck("DynamicAttribute", "dynamic_attribute"),),
        required_test_data=("Configured dynamic attribute", "Target su_id"),
        verification="api+db",
        cleanup="Restore previous dynamic attribute values",
        severity="medium",
        keywords=("dynamic", "attribute", "custom field", "field"),
    ),
    FunctionDefinition(
        id="history.audit",
        display_name="History and audit",
        category="History",
        subcategory="Geometry, survey, attribute, RRR history",
        frontend="side panels, report dialogs",
        endpoints=(
            EndpointCheck("GET", "/survey_rep_history_username/", "Load survey history by user"),
            EndpointCheck("GET", "/history-spartialunit-attrib-username/", "Load attribute history by user"),
            EndpointCheck("GET", "/rrr-history/", "Load RRR audit history"),
        ),
        db_checks=(
            DbCheck("SurveyRepHistory", "survey_rep_history"),
            DbCheck("History_Spartialunit_Attrib", "history_spartialunit_attrib"),
        ),
        required_test_data=("Authenticated user with prior edits"),
        verification="api+db",
        cleanup="None",
        severity="high",
        keywords=("history", "audit", "log", "change", "tracking"),
    ),
    FunctionDefinition(
        id="lookups.reference",
        display_name="Lookup and reference data",
        category="Lookups",
        subcategory="LADM and Sri Lanka reference lists",
        frontend="dropdowns across admin, land, building, party, RRR forms",
        endpoints=(
            EndpointCheck("GET", "/lst-sl-party-type-1/", "Party types"),
            EndpointCheck("GET", "/lst-sl-righttype-9/", "Right types"),
            EndpointCheck("GET", "/lst-gnd-area/", "GND reference area"),
            EndpointCheck("GET", "/lst-su-sl-structuretype-21/", "Structure types"),
        ),
        db_checks=(DbCheck("Lookup tables", "lst_*"),),
        required_test_data=("Seeded lookup data"),
        verification="api+db",
        cleanup="None",
        severity="medium",
        keywords=("lookup", "dropdown", "gnd", "reference", "type", "list"),
    ),
    FunctionDefinition(
        id="communication.workflow",
        display_name="Communication and workflow utilities",
        category="Communication",
        subcategory="Messages, inquiries, reminders, tags",
        frontend="dialogs/admin-contact, dialogs/online-users, shared popups",
        endpoints=(
            EndpointCheck("GET", "/messages/", "List messages"),
            EndpointCheck("GET", "/inquiries/", "List inquiries"),
            EndpointCheck("GET", "/reminders/", "List reminders"),
            EndpointCheck("GET", "/tags/", "List tags"),
        ),
        db_checks=(
            DbCheck("Messages", "messages"),
            DbCheck("Inquiries", "inquiries"),
            DbCheck("Reminders", "reminders"),
            DbCheck("Tags", "tags"),
        ),
        required_test_data=("Authenticated user",),
        verification="api+db",
        cleanup="None for read-only checks",
        severity="low",
        keywords=("message", "inquiry", "reminder", "tag", "contact"),
    ),
)


def all_functions() -> list[FunctionDefinition]:
    return list(FUNCTIONS)


def get_function(function_id: str) -> FunctionDefinition:
    for fn in FUNCTIONS:
        if fn.id == function_id:
            return fn
    raise KeyError(f"Unknown function id: {function_id}")


def categories() -> list[str]:
    return sorted({fn.category for fn in FUNCTIONS})


def functions_by_category(category: str) -> list[FunctionDefinition]:
    return [fn for fn in FUNCTIONS if fn.category.lower() == category.lower()]

