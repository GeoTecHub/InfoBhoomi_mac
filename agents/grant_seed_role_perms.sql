-- ============================================================================
-- InfoBhoomi — grant the seed user's role the missing attribute permissions
-- ============================================================================
-- The data seeder writes through permission-gated update endpoints. The role
-- for user 'admin_bw' is missing role_permission rows for these field groups,
-- so the API accepts the PATCH (HTTP 200) but silently discards the value:
--
--   Land · Zoning        : perms 48-54
--   Land · Physical Env  : perms 43-47
--   Land · Tax           : perms 56,57,58
--   Building · Admin     : perms 156,157,158  (structure_type, condition, construction_year)
--
-- Role-permission rows are only created when a role is created (bulk_create in
-- User_Roles_Create_View), so permissions added to the catalog *after* this role
-- was created never got a row — and the /role-permission/update/ API can only
-- PATCH existing rows, not insert new ones. Hence this one-off INSERT.
--
-- Safe to run more than once: the NOT EXISTS guard skips rows that already exist.
-- Change 'admin_bw' below if you seed as a different user.
-- ============================================================================

INSERT INTO role_permission (role_id, permission_id, "view", "add", edit, "delete")
SELECT r.role_id, v.pid, TRUE, TRUE, TRUE, FALSE
FROM (
    SELECT ur.role_id
    FROM user_roles ur
    JOIN user_user uu ON uu.id = ANY (ur.users)
    WHERE uu.username = 'admin_bw'
    ORDER BY ur.role_id
    LIMIT 1
) AS r
CROSS JOIN (VALUES
    (43), (44), (45), (46), (47),            -- Physical Env
    (48), (49), (50), (51), (52), (53), (54),-- Zoning
    (56), (57), (58),                        -- Tax (land_value, market_value, tax_status)
    (156), (157), (158)                      -- Building admin (construction_year, structure_type, condition)
) AS v(pid)
WHERE NOT EXISTS (
    SELECT 1 FROM role_permission rp
    WHERE rp.role_id = r.role_id
      AND rp.permission_id = v.pid
);

-- Verify what the role now has for these permissions:
-- SELECT rp.permission_id, rp."view", rp.edit
-- FROM role_permission rp
-- JOIN user_roles ur ON ur.role_id = rp.role_id
-- JOIN user_user uu ON uu.id = ANY (ur.users)
-- WHERE uu.username = 'admin_bw'
--   AND rp.permission_id IN (43,44,45,46,47,48,49,50,51,52,53,54,56,57,58,156,157,158)
-- ORDER BY rp.permission_id;
