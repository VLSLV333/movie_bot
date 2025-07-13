-- SQL script to check and fix upload account distribution
-- Run this script to diagnose and fix account initialization issues

-- 1. Check current account distribution
SELECT 
    'Current Database State' as info,
    COUNT(*) as total_accounts,
    COUNT(CASE WHEN today_uploads = 0 THEN 1 END) as unused_accounts,
    COUNT(CASE WHEN today_uploads > 0 THEN 1 END) as used_accounts
FROM upload_account_stats;

-- 2. Show detailed account usage
SELECT 
    session_name,
    today_uploads,
    total_uploads,
    last_upload_date,
    last_upload_time,
    last_error
FROM upload_account_stats 
ORDER BY today_uploads ASC, total_uploads ASC;

-- 3. Check for accounts with zero usage (these should be the least used)
SELECT 
    session_name,
    today_uploads,
    total_uploads,
    'This account will be selected first' as note
FROM upload_account_stats 
WHERE today_uploads = 0
ORDER BY total_uploads ASC;

-- 4. If you need to manually insert missing accounts, use this template:
-- (Replace 'session_name' with actual session names from your config)
/*
INSERT INTO upload_account_stats (session_name, total_uploads, today_uploads, last_upload_date)
VALUES 
    ('session2', 0, 0, CURRENT_DATE),
    ('session3', 0, 0, CURRENT_DATE),
    ('session4', 0, 0, CURRENT_DATE),
    ('session5', 0, 0, CURRENT_DATE),
    ('session6', 0, 0, CURRENT_DATE),
    ('session7', 0, 0, CURRENT_DATE),
    ('session8', 0, 0, CURRENT_DATE),
    ('session9', 0, 0, CURRENT_DATE),
    ('session10', 0, 0, CURRENT_DATE)
ON CONFLICT (session_name) DO NOTHING;
*/

-- 5. Reset all accounts to zero usage (use with caution!)
-- This will make all accounts equally "least used"
/*
UPDATE upload_account_stats 
SET today_uploads = 0, last_upload_date = CURRENT_DATE
WHERE session_name IN ('session1', 'session2', 'session3', 'session4', 'session5', 
                      'session6', 'session7', 'session8', 'session9', 'session10');
*/ 