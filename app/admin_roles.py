"""Grant existing volunteers a separate, auditable administrator identity."""
from .db import Database, one


def migrate(settings):
    with Database(settings).transaction(True) as c:
        c.execute("SHOW COLUMNS FROM admin LIKE 'student_id'")
        if not c.fetchone():
            c.execute('''ALTER TABLE admin ADD student_id VARCHAR(32) NULL,
                ADD UNIQUE KEY uq_admin_student(student_id),
                ADD CONSTRAINT fk_admin_student FOREIGN KEY(student_id) REFERENCES student(student_id)''')


class AdministratorService:
    def promote_student(self, actor, student_id, reason, slot_ids=()):
        from .service import require, reason_text
        reason = reason_text(reason)
        with self.db.transaction(True) as c:
            a = self.actor(c, actor, ('SUPER',))
            student = one(c, 'SELECT * FROM student WHERE student_id=%s FOR UPDATE', (student_id,))
            require(student, '队员不存在', 404)
            require(student['status'] == 'ACTIVE', '只能将正常在队的队员设为普通管理员')
            slots = []
            for slot_id in sorted(set(slot_ids)):
                slot = self.slot(c, slot_id)
                require(slot.get('weekday') is not None and slot['status'] == 'ACTIVE', '请选择启用的固定时段', 422)
                slots.append(slot)
            admin = one(c, 'SELECT * FROM admin WHERE student_id=%s', (student_id,))
            changed = False
            if admin:
                require(admin['role'] == 'NORMAL', '该队员已关联其他管理角色，不能覆盖')
                admin_id = admin['admin_id']
                if admin['status'] != 'ACTIVE':
                    c.execute("UPDATE admin SET status='ACTIVE' WHERE admin_id=%s", (admin_id,))
                    changed = True
            else:
                require(not one(c, 'SELECT 1 FROM admin WHERE account=%s', (student_id,)),
                        '该学号已被其他管理员账号占用，请先核对管理员资料')
                c.execute('''INSERT INTO admin(name,account,password_hash,role,student_id)
                    VALUES(%s,%s,%s,'NORMAL',%s)''',
                    (student['name'], student_id, student['password_hash'], student_id))
                admin_id, changed = c.lastrowid, True
            previous = [{'slot_id':s['slot_id'],'manager_admin_id':s['manager_admin_id']} for s in slots]
            for slot in slots:
                if slot['manager_admin_id'] != admin_id:
                    c.execute('UPDATE service_slot SET manager_admin_id=%s WHERE slot_id=%s', (admin_id,slot['slot_id']))
                    changed = True
            result = {'admin_id':admin_id,'student_id':student_id,'account':student_id,
                      'role':'NORMAL','slot_ids':[s['slot_id'] for s in slots],'replayed':not changed}
            if changed:
                self.sync_semesters(c)
                self.audit(c, a['_id'], 'PROMOTE_STUDENT', 'admin', admin_id,
                           {'admin_status':admin['status'] if admin else None,'slots':previous}, result, reason)
            return result
