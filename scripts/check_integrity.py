"""Read-only accounting and authorization diagnostics; prints counts, no credentials."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import Database,one,all_rows


def check(db=None):
    db=db or Database()
    queries={
      'orphan_service_records':'''SELECT COUNT(*) n FROM service_record r LEFT JOIN attendance a ON a.attendance_id=r.attendance_id LEFT JOIN schedule s ON s.schedule_id=a.schedule_id LEFT JOIN student st ON st.student_id=s.student_id WHERE a.attendance_id IS NULL OR s.schedule_id IS NULL OR st.student_id IS NULL''',
      'valid_hours_on_cancelled_schedule':'''SELECT COUNT(*) n FROM service_record r JOIN attendance a ON a.attendance_id=r.attendance_id JOIN schedule s ON s.schedule_id=a.schedule_id WHERE r.record_status='VALID' AND r.service_minutes>0 AND s.status='CANCELLED' ''',
      'valid_hours_on_absence_or_leave':'''SELECT COUNT(*) n FROM service_record r JOIN attendance a ON a.attendance_id=r.attendance_id WHERE r.record_status='VALID' AND r.service_minutes>0 AND a.attendance_status IN ('ABSENT','LEAVE')''',
      'invalid_minutes':"SELECT COUNT(*) n FROM service_record WHERE service_minutes<0 OR service_minutes>1440",
      'credit_score_latest_log_mismatch':'''SELECT COUNT(*) n FROM student s JOIN credit_log l ON l.student_id=s.student_id LEFT JOIN credit_log later ON later.student_id=l.student_id AND later.credit_log_id>l.credit_log_id WHERE later.credit_log_id IS NULL AND s.credit_score<>l.after_score''',
      'credit_log_arithmetic_error':"SELECT COUNT(*) n FROM credit_log WHERE after_score<>before_score+change_score",
      'claim_group_business_mismatch':'''SELECT COUNT(*) n FROM hour_collection h JOIN business_group g ON g.group_id=h.group_id WHERE h.business_id<>g.business_id''',
      'approved_claim_missing_ledger':'''SELECT COUNT(*) n FROM hour_submission h LEFT JOIN schedule s ON s.schedule_id=h.schedule_id LEFT JOIN attendance a ON a.schedule_id=s.schedule_id LEFT JOIN service_record r ON r.attendance_id=a.attendance_id WHERE h.status='APPROVED' AND (s.schedule_id IS NULL OR r.record_id IS NULL OR r.record_status<>'VALID')''',
      'unapproved_claim_with_valid_ledger':'''SELECT COUNT(*) n FROM hour_submission h JOIN attendance a ON a.schedule_id=h.schedule_id JOIN service_record r ON r.attendance_id=a.attendance_id WHERE h.status<>'APPROVED' AND r.record_status='VALID' AND r.service_minutes>0''',
      'group_snapshot_mismatch':'''SELECT COUNT(*) n FROM hour_submission h JOIN collection_item i ON i.item_id=h.item_id JOIN hour_collection c ON c.collection_id=i.collection_id JOIN schedule s ON s.schedule_id=h.schedule_id WHERE NOT(s.group_id <=> c.group_id)''',
      'archived_business_open_window':"SELECT COUNT(*) n FROM business b JOIN business_window w ON w.business_id=b.business_id WHERE b.status='ARCHIVED' AND w.active_until IS NULL",
      'active_fixed_slots_without_manager':'''SELECT COUNT(*) n FROM service_slot s JOIN business b ON b.business_id=s.business_id LEFT JOIN admin a ON a.admin_id=s.manager_admin_id WHERE b.status='ACTIVE' AND s.status='ACTIVE' AND s.schedule_kind IN ('FIXED','WEEKLY') AND (a.admin_id IS NULL OR a.status<>'ACTIVE')''',
    }
    with db.transaction() as c:
        results={name:int(one(c,sql)['n']) for name,sql in queries.items()}
        totals=one(c,"SELECT COUNT(*) records,COALESCE(SUM(service_minutes),0) minutes FROM service_record WHERE record_status='VALID'")
        result={'checks':results,'valid_records':int(totals['records']),'valid_minutes':int(totals['minutes']),
                'tables':int(one(c,'SELECT COUNT(*) n FROM information_schema.tables WHERE table_schema=DATABASE()')['n']),
                'businesses':all_rows(c,'SELECT status,COUNT(*) count FROM business GROUP BY status'),
                'unassigned_collection_businesses':all_rows(c,"SELECT b.name FROM business b WHERE b.kind='EVENT' AND b.status='ACTIVE' AND NOT EXISTS(SELECT 1 FROM collection_manager m JOIN admin a ON a.admin_id=m.admin_id WHERE m.business_id=b.business_id AND a.status='ACTIVE') AND NOT EXISTS(SELECT 1 FROM collection_group_manager m JOIN business_group g ON g.group_id=m.group_id JOIN admin a ON a.admin_id=m.admin_id WHERE g.business_id=b.business_id AND a.status='ACTIVE')")}
    result['all_checks_passed']=not any(results.values())
    return result


if __name__=='__main__':print(json.dumps(check(),ensure_ascii=False,indent=2))
