-- Row validations shared by MySQL 5.7.44 and 8.0.
-- MySQL 5.7 does not enforce CHECK clauses. These triggers enforce the same rules.
-- Install after schema.sql and before adding seed or application data.

DELIMITER $$

CREATE TRIGGER bi_student_validate BEFORE INSERT ON student
FOR EACH ROW
BEGIN
    IF NEW.credit_score < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'student.credit_score must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bu_student_validate BEFORE UPDATE ON student
FOR EACH ROW
BEGIN
    IF NEW.credit_score < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'student.credit_score must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bi_service_slot_validate BEFORE INSERT ON service_slot
FOR EACH ROW
BEGIN
    IF NEW.period_no <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.period_no must be positive';
    END IF;
    IF NEW.end_time <= NEW.start_time THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.end_time must follow start_time';
    END IF;
    IF NEW.need_num <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.need_num must be positive';
    END IF;
    IF NEW.service_minutes <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.service_minutes must be positive';
    END IF;
END$$

CREATE TRIGGER bu_service_slot_validate BEFORE UPDATE ON service_slot
FOR EACH ROW
BEGIN
    IF NEW.period_no <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.period_no must be positive';
    END IF;
    IF NEW.end_time <= NEW.start_time THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.end_time must follow start_time';
    END IF;
    IF NEW.need_num <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.need_num must be positive';
    END IF;
    IF NEW.service_minutes <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_slot.service_minutes must be positive';
    END IF;
END$$

CREATE TRIGGER bi_service_record_validate BEFORE INSERT ON service_record
FOR EACH ROW
BEGIN
    IF NEW.service_minutes < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_record.service_minutes must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bu_service_record_validate BEFORE UPDATE ON service_record
FOR EACH ROW
BEGIN
    IF NEW.service_minutes < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'service_record.service_minutes must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bi_credit_rule_validate BEFORE INSERT ON credit_rule
FOR EACH ROW
BEGIN
    IF NEW.version <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_rule.version must be positive';
    END IF;
    IF NEW.deduct_score < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_rule.deduct_score must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bu_credit_rule_validate BEFORE UPDATE ON credit_rule
FOR EACH ROW
BEGIN
    IF NEW.version <= 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_rule.version must be positive';
    END IF;
    IF NEW.deduct_score < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_rule.deduct_score must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bi_violation_validate BEFORE INSERT ON violation
FOR EACH ROW
BEGIN
    IF NEW.nominal_deduct < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'violation.nominal_deduct must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bu_violation_validate BEFORE UPDATE ON violation
FOR EACH ROW
BEGIN
    IF NEW.nominal_deduct < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'violation.nominal_deduct must be nonnegative';
    END IF;
END$$

CREATE TRIGGER bi_credit_log_validate BEFORE INSERT ON credit_log
FOR EACH ROW
BEGIN
    IF NEW.before_score < 0 OR NEW.after_score < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_log scores must be nonnegative';
    END IF;
    IF NEW.after_score <> NEW.before_score + NEW.change_score THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_log after_score must equal before_score plus change_score';
    END IF;
END$$

CREATE TRIGGER bu_credit_log_validate BEFORE UPDATE ON credit_log
FOR EACH ROW
BEGIN
    IF NEW.before_score < 0 OR NEW.after_score < 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_log scores must be nonnegative';
    END IF;
    IF NEW.after_score <> NEW.before_score + NEW.change_score THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'credit_log after_score must equal before_score plus change_score';
    END IF;
END$$

DELIMITER ;
