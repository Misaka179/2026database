-- MySQL 5.7.44 and 8.0. Run against the intended empty application database.
-- Database creation and connection configuration are handled by the initializer.
-- Install constraints.sql immediately after these tables to enforce row validations.

CREATE TABLE student (
    student_id VARCHAR(32) NOT NULL,
    name VARCHAR(100) NOT NULL,
    college VARCHAR(100) NULL,
    phone VARCHAR(32) NULL,
    password_hash VARCHAR(255) NOT NULL,
    credit_score INT NOT NULL DEFAULT 5,
    credit_version INT NOT NULL DEFAULT 1,
    disabled_by_credit TINYINT NOT NULL DEFAULT 0,
    status ENUM('ACTIVE', 'QUIT', 'DISABLED') NOT NULL DEFAULT 'ACTIVE',
    join_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (student_id),
    INDEX idx_student_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE admin (
    admin_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    name VARCHAR(100) NOT NULL,
    account VARCHAR(64) NOT NULL,
    student_id VARCHAR(32) NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('NORMAL', 'SUPER') NOT NULL DEFAULT 'NORMAL',
    status ENUM('ACTIVE', 'DISABLED') NOT NULL DEFAULT 'ACTIVE',
    PRIMARY KEY (admin_id),
    UNIQUE KEY uq_admin_account (account),
    UNIQUE KEY uq_admin_student (student_id),
    CONSTRAINT fk_admin_student FOREIGN KEY(student_id) REFERENCES student(student_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE service_slot (
    slot_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    team_name VARCHAR(100) NOT NULL,
    period_no INT NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    location VARCHAR(200) NOT NULL,
    need_num INT NOT NULL,
    service_minutes INT NOT NULL,
    manager_admin_id BIGINT UNSIGNED NOT NULL,
    status ENUM('ACTIVE', 'DISABLED') NOT NULL DEFAULT 'ACTIVE',
    PRIMARY KEY (slot_id),
    CONSTRAINT fk_slot_manager FOREIGN KEY (manager_admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_slot_manager_status (manager_admin_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE schedule (
    schedule_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    slot_id BIGINT UNSIGNED NOT NULL,
    admin_id BIGINT UNSIGNED NOT NULL,
    schedule_date DATE NOT NULL,
    semester_id BIGINT UNSIGNED NULL,
    week_no INT NULL,
    cancel_reason VARCHAR(24) NULL,
    status ENUM('ACTIVE', 'CANCELLED', 'COMPLETED') NOT NULL DEFAULT 'ACTIVE',
    create_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    active_marker TINYINT GENERATED ALWAYS AS
        (CASE WHEN status IN ('ACTIVE', 'COMPLETED') THEN 1 ELSE NULL END) STORED,
    PRIMARY KEY (schedule_id),
    UNIQUE KEY uq_schedule_id_student (schedule_id, student_id),
    UNIQUE KEY uq_schedule_effective (student_id, slot_id, schedule_date, active_marker),
    CONSTRAINT fk_schedule_student FOREIGN KEY (student_id)
        REFERENCES student (student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_schedule_slot FOREIGN KEY (slot_id)
        REFERENCES service_slot (slot_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_schedule_admin FOREIGN KEY (admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_schedule_student_date (student_id, schedule_date, status),
    INDEX idx_schedule_slot_date (slot_id, schedule_date, status),
    INDEX idx_schedule_date_status (schedule_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE attendance (
    attendance_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    schedule_id BIGINT UNSIGNED NOT NULL,
    admin_id BIGINT UNSIGNED NOT NULL,
    attendance_status ENUM('NORMAL', 'LATE', 'ABSENT', 'LEAVE') NOT NULL,
    source VARCHAR(24) NOT NULL DEFAULT 'MANUAL',
    revision INT NOT NULL DEFAULT 1,
    check_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    remark VARCHAR(1000) NULL,
    PRIMARY KEY (attendance_id),
    UNIQUE KEY uq_attendance_schedule (schedule_id),
    CONSTRAINT fk_attendance_schedule FOREIGN KEY (schedule_id)
        REFERENCES schedule (schedule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_attendance_admin FOREIGN KEY (admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE service_record (
    record_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    attendance_id BIGINT UNSIGNED NOT NULL,
    service_minutes INT NOT NULL,
    record_status ENUM('VALID', 'VOID') NOT NULL DEFAULT 'VALID',
    create_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (record_id),
    UNIQUE KEY uq_service_record_attendance (attendance_id),
    CONSTRAINT fk_record_attendance FOREIGN KEY (attendance_id)
        REFERENCES attendance (attendance_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE leave_application (
    leave_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    schedule_id BIGINT UNSIGNED NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    apply_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    approve_admin_id BIGINT UNSIGNED NULL,
    approve_status ENUM('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED') NOT NULL DEFAULT 'PENDING',
    approve_time DATETIME(6) NULL,
    active_marker TINYINT GENERATED ALWAYS AS
        (CASE WHEN approve_status IN ('PENDING', 'APPROVED') THEN 1 ELSE NULL END) STORED,
    PRIMARY KEY (leave_id),
    UNIQUE KEY uq_leave_effective (schedule_id, active_marker),
    CONSTRAINT fk_leave_student FOREIGN KEY (student_id)
        REFERENCES student (student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_leave_schedule_student FOREIGN KEY (schedule_id, student_id)
        REFERENCES schedule (schedule_id, student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_leave_admin FOREIGN KEY (approve_admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_leave_student_time (student_id, apply_time),
    INDEX idx_leave_approval (approve_status, apply_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE transfer_application (
    transfer_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    old_schedule_id BIGINT UNSIGNED NOT NULL,
    new_slot_id BIGINT UNSIGNED NOT NULL,
    new_date DATE NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    apply_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    first_admin_id BIGINT UNSIGNED NULL,
    first_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    first_time DATETIME(6) NULL,
    final_admin_id BIGINT UNSIGNED NULL,
    final_status ENUM('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED') NOT NULL DEFAULT 'PENDING',
    final_time DATETIME(6) NULL,
    new_schedule_id BIGINT UNSIGNED NULL,
    active_marker TINYINT GENERATED ALWAYS AS
        (CASE WHEN first_status <> 'REJECTED' AND final_status = 'PENDING' THEN 1 ELSE NULL END) STORED,
    PRIMARY KEY (transfer_id),
    UNIQUE KEY uq_transfer_pending (old_schedule_id, active_marker),
    CONSTRAINT fk_transfer_student FOREIGN KEY (student_id)
        REFERENCES student (student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_transfer_old_schedule_student FOREIGN KEY (old_schedule_id, student_id)
        REFERENCES schedule (schedule_id, student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_transfer_slot FOREIGN KEY (new_slot_id)
        REFERENCES service_slot (slot_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_transfer_first_admin FOREIGN KEY (first_admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_transfer_final_admin FOREIGN KEY (final_admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_transfer_new_schedule_student FOREIGN KEY (new_schedule_id, student_id)
        REFERENCES schedule (schedule_id, student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_transfer_student_time (student_id, apply_time),
    INDEX idx_transfer_approval (final_status, first_status, apply_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE withdrawal_application (
    withdrawal_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    apply_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    admin_id BIGINT UNSIGNED NULL,
    approve_status ENUM('PENDING', 'APPROVED', 'REJECTED') NOT NULL DEFAULT 'PENDING',
    approve_time DATETIME(6) NULL,
    active_marker TINYINT GENERATED ALWAYS AS
        (CASE WHEN approve_status = 'PENDING' THEN 1 ELSE NULL END) STORED,
    PRIMARY KEY (withdrawal_id),
    UNIQUE KEY uq_withdrawal_pending (student_id, active_marker),
    CONSTRAINT fk_withdrawal_student FOREIGN KEY (student_id)
        REFERENCES student (student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_withdrawal_admin FOREIGN KEY (admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_withdrawal_approval (approve_status, apply_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE credit_rule (
    rule_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    violation_type ENUM('LATE', 'ABSENT') NOT NULL,
    version INT NOT NULL,
    deduct_score INT NOT NULL,
    status ENUM('ACTIVE', 'RETIRED') NOT NULL DEFAULT 'ACTIVE',
    create_admin_id BIGINT UNSIGNED NOT NULL,
    create_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    active_marker TINYINT GENERATED ALWAYS AS
        (CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END) STORED,
    PRIMARY KEY (rule_id),
    UNIQUE KEY uq_rule_type_version (violation_type, version),
    UNIQUE KEY uq_rule_active (violation_type, active_marker),
    CONSTRAINT fk_rule_admin FOREIGN KEY (create_admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE violation (
    violation_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    attendance_id BIGINT UNSIGNED NOT NULL,
    rule_id BIGINT UNSIGNED NOT NULL,
    nominal_deduct INT NOT NULL,
    status ENUM('VALID', 'REVOKED') NOT NULL DEFAULT 'VALID',
    create_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (violation_id),
    active_marker TINYINT GENERATED ALWAYS AS (CASE WHEN status='VALID' THEN 1 ELSE NULL END) STORED,
    INDEX idx_violation_attendance (attendance_id),
    UNIQUE KEY uq_violation_active (attendance_id,active_marker),
    UNIQUE KEY uq_violation_id_rule (violation_id, rule_id),
    CONSTRAINT fk_violation_attendance FOREIGN KEY (attendance_id)
        REFERENCES attendance (attendance_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_violation_rule FOREIGN KEY (rule_id)
        REFERENCES credit_rule (rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE credit_log (
    credit_log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    student_id VARCHAR(32) NOT NULL,
    violation_id BIGINT UNSIGNED NULL,
    rule_id BIGINT UNSIGNED NULL,
    operator_id BIGINT UNSIGNED NOT NULL,
    change_score INT NOT NULL,
    before_score INT NOT NULL,
    after_score INT NOT NULL,
    change_reason VARCHAR(1000) NOT NULL,
    change_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    entry_type VARCHAR(24) NOT NULL DEFAULT 'DEDUCTION',
    reverses_log_id BIGINT UNSIGNED NULL,
    PRIMARY KEY (credit_log_id),
    INDEX idx_credit_log_violation (violation_id),
    UNIQUE KEY uq_credit_reversal (reverses_log_id),
    CONSTRAINT fk_credit_reversal FOREIGN KEY (reverses_log_id) REFERENCES credit_log(credit_log_id),
    CONSTRAINT fk_credit_log_student FOREIGN KEY (student_id)
        REFERENCES student (student_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_credit_log_violation_rule FOREIGN KEY (violation_id, rule_id)
        REFERENCES violation (violation_id, rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_credit_log_rule FOREIGN KEY (rule_id)
        REFERENCES credit_rule (rule_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    CONSTRAINT fk_credit_log_operator FOREIGN KEY (operator_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_credit_log_student_time (student_id, change_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE operation_log (
    log_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    admin_id BIGINT UNSIGNED NOT NULL,
    operation_type VARCHAR(64) NOT NULL,
    target_table VARCHAR(64) NOT NULL,
    target_id VARCHAR(64) NOT NULL,
    before_value JSON NULL,
    after_value JSON NULL,
    reason VARCHAR(1000) NOT NULL,
    operation_time DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (log_id),
    CONSTRAINT fk_operation_log_admin FOREIGN KEY (admin_id)
        REFERENCES admin (admin_id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    INDEX idx_operation_log_target (target_table, target_id, operation_time),
    INDEX idx_operation_log_admin_time (admin_id, operation_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
