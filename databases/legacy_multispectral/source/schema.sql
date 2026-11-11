CREATE DATABASE IF NOT EXISTS lettuce_multispectral
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE lettuce_multispectral;

CREATE TABLE IF NOT EXISTS crop_batches (
  id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  batch_code VARCHAR(32) NOT NULL,
  started_on DATE NOT NULL,
  ended_on DATE NULL,
  notes TEXT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_crop_batches_code (batch_code)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS light_conditions (
  id TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(3) NOT NULL,
  rack_code CHAR(1) NOT NULL,
  level_no TINYINT UNSIGNED NOT NULL,
  display_order TINYINT UNSIGNED NOT NULL,
  light_name VARCHAR(100) NULL,
  notes TEXT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_light_conditions_code (code),
  UNIQUE KEY uq_light_conditions_position (rack_code, level_no),
  UNIQUE KEY uq_light_conditions_order (display_order),
  CONSTRAINT chk_light_rack CHECK (rack_code IN ('A', 'B', 'C', 'D')),
  CONSTRAINT chk_light_level CHECK (level_no BETWEEN 1 AND 3)
) ENGINE = InnoDB;

INSERT INTO light_conditions (code, rack_code, level_no, display_order)
VALUES
  ('A-1', 'A', 1, 1), ('A-2', 'A', 2, 2), ('A-3', 'A', 3, 3),
  ('B-1', 'B', 1, 4), ('B-2', 'B', 2, 5), ('B-3', 'B', 3, 6),
  ('C-1', 'C', 1, 7), ('C-2', 'C', 2, 8), ('C-3', 'C', 3, 9),
  ('D-1', 'D', 1, 10), ('D-2', 'D', 2, 11), ('D-3', 'D', 3, 12)
ON DUPLICATE KEY UPDATE
  rack_code = VALUES(rack_code),
  level_no = VALUES(level_no),
  display_order = VALUES(display_order);

CREATE TABLE IF NOT EXISTS spectral_bands (
  id TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
  code VARCHAR(8) NOT NULL,
  wavelength_nm SMALLINT UNSIGNED NOT NULL,
  display_order TINYINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_spectral_bands_code (code),
  UNIQUE KEY uq_spectral_bands_wavelength (wavelength_nm),
  UNIQUE KEY uq_spectral_bands_order (display_order)
) ENGINE = InnoDB;

INSERT INTO spectral_bands (code, wavelength_nm, display_order)
VALUES
  ('L405', 405, 1), ('L430', 430, 2), ('L450', 450, 3),
  ('L475', 475, 4), ('L500', 500, 5), ('L540', 540, 6),
  ('L600', 600, 7), ('L630', 630, 8), ('L680', 680, 9),
  ('L700', 700, 10), ('L730', 730, 11), ('L770', 770, 12),
  ('L800', 800, 13), ('L850', 850, 14), ('L900', 900, 15),
  ('L980', 980, 16)
ON DUPLICATE KEY UPDATE
  wavelength_nm = VALUES(wavelength_nm),
  display_order = VALUES(display_order);

CREATE TABLE IF NOT EXISTS plants (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  batch_id SMALLINT UNSIGNED NOT NULL,
  light_condition_id TINYINT UNSIGNED NOT NULL,
  position_no TINYINT UNSIGNED NOT NULL,
  plant_code VARCHAR(64) NULL,
  notes TEXT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_plants_position (batch_id, light_condition_id, position_no),
  CONSTRAINT fk_plants_batch FOREIGN KEY (batch_id) REFERENCES crop_batches (id),
  CONSTRAINT fk_plants_light FOREIGN KEY (light_condition_id) REFERENCES light_conditions (id),
  CONSTRAINT chk_plant_position CHECK (position_no BETWEEN 1 AND 12)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS source_folders (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  batch_id SMALLINT UNSIGNED NOT NULL,
  folder_name VARCHAR(255) NOT NULL,
  folder_path VARCHAR(1024) NOT NULL,
  source_path_hash BINARY(32) NOT NULL,
  capture_date DATE NOT NULL,
  acquisition_no SMALLINT UNSIGNED NULL,
  rack_code CHAR(1) NOT NULL,
  capture_set_count SMALLINT UNSIGNED NOT NULL,
  mapping_status VARCHAR(20) NOT NULL,
  imported_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_source_folders_path_hash (source_path_hash),
  KEY ix_source_folders_date_rack (capture_date, rack_code),
  CONSTRAINT fk_source_folders_batch FOREIGN KEY (batch_id) REFERENCES crop_batches (id),
  CONSTRAINT chk_source_folder_rack CHECK (rack_code IN ('A', 'B', 'C', 'D')),
  CONSTRAINT chk_source_folder_status CHECK (mapping_status IN ('AUTO', 'OVERRIDE', 'NEEDS_REVIEW'))
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS capture_groups (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_folder_id BIGINT UNSIGNED NOT NULL,
  light_condition_id TINYINT UNSIGNED NULL,
  captured_at DATETIME NOT NULL,
  source_timestamp CHAR(19) NOT NULL,
  sequence_in_folder SMALLINT UNSIGNED NOT NULL,
  group_no TINYINT UNSIGNED NULL,
  plants_per_image TINYINT UNSIGNED NULL,
  first_plant_position TINYINT UNSIGNED NULL,
  last_plant_position TINYINT UNSIGNED NULL,
  mapping_status VARCHAR(16) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_capture_groups_time (source_folder_id, captured_at),
  KEY ix_capture_groups_comparison (light_condition_id, captured_at),
  CONSTRAINT fk_capture_groups_folder FOREIGN KEY (source_folder_id) REFERENCES source_folders (id),
  CONSTRAINT fk_capture_groups_light FOREIGN KEY (light_condition_id) REFERENCES light_conditions (id),
  CONSTRAINT chk_capture_group_status CHECK (mapping_status IN ('AUTO', 'OVERRIDE', 'UNMAPPED', 'EXCLUDED'))
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS capture_group_plants (
  capture_group_id BIGINT UNSIGNED NOT NULL,
  plant_id BIGINT UNSIGNED NOT NULL,
  slot_no TINYINT UNSIGNED NOT NULL,
  PRIMARY KEY (capture_group_id, plant_id),
  UNIQUE KEY uq_capture_group_slot (capture_group_id, slot_no),
  CONSTRAINT fk_capture_group_plants_group FOREIGN KEY (capture_group_id) REFERENCES capture_groups (id),
  CONSTRAINT fk_capture_group_plants_plant FOREIGN KEY (plant_id) REFERENCES plants (id)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS multispectral_images (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  capture_group_id BIGINT UNSIGNED NOT NULL,
  band_id TINYINT UNSIGNED NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_path VARCHAR(1024) NOT NULL,
  file_path_hash BINARY(32) NOT NULL,
  file_size_bytes BIGINT UNSIGNED NOT NULL,
  file_modified_at DATETIME NULL,
  content_sha256 BINARY(32) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_multispectral_group_band (capture_group_id, band_id),
  UNIQUE KEY uq_multispectral_path_hash (file_path_hash),
  CONSTRAINT fk_multispectral_group FOREIGN KEY (capture_group_id) REFERENCES capture_groups (id),
  CONSTRAINT fk_multispectral_band FOREIGN KEY (band_id) REFERENCES spectral_bands (id)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS auxiliary_images (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  capture_group_id BIGINT UNSIGNED NOT NULL,
  product_code VARCHAR(16) NOT NULL,
  file_name VARCHAR(255) NOT NULL,
  file_path VARCHAR(1024) NOT NULL,
  file_path_hash BINARY(32) NOT NULL,
  file_size_bytes BIGINT UNSIGNED NOT NULL,
  file_modified_at DATETIME NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_auxiliary_group_product (capture_group_id, product_code),
  UNIQUE KEY uq_auxiliary_path_hash (file_path_hash),
  CONSTRAINT fk_auxiliary_group FOREIGN KEY (capture_group_id) REFERENCES capture_groups (id),
  CONSTRAINT chk_auxiliary_product CHECK (product_code IN ('COLOR', 'NDVI', 'NDRE'))
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS image_measurements (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  capture_group_id BIGINT UNSIGNED NOT NULL,
  plant_id BIGINT UNSIGNED NULL,
  band_id TINYINT UNSIGNED NULL,
  metric_code VARCHAR(64) NOT NULL,
  metric_value DOUBLE NOT NULL,
  unit VARCHAR(32) NULL,
  algorithm_version VARCHAR(64) NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_measurements_metric (metric_code, capture_group_id),
  CONSTRAINT fk_measurements_group FOREIGN KEY (capture_group_id) REFERENCES capture_groups (id),
  CONSTRAINT fk_measurements_plant FOREIGN KEY (plant_id) REFERENCES plants (id),
  CONSTRAINT fk_measurements_band FOREIGN KEY (band_id) REFERENCES spectral_bands (id)
) ENGINE = InnoDB;

CREATE TABLE IF NOT EXISTS environment_log_samples (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  source_folder_id BIGINT UNSIGNED NOT NULL,
  sequence_no INT UNSIGNED NOT NULL,
  instrument_seconds DECIMAL(20, 6) NOT NULL,
  recorded_at DATETIME(3) NULL,
  value_1 DOUBLE NULL,
  value_2 DOUBLE NULL,
  value_3 DOUBLE NULL,
  value_4 DOUBLE NULL,
  value_5 DOUBLE NULL,
  value_6 DOUBLE NULL,
  raw_line VARCHAR(512) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_environment_log_row (source_folder_id, sequence_no),
  CONSTRAINT fk_environment_log_folder FOREIGN KEY (source_folder_id) REFERENCES source_folders (id)
) ENGINE = InnoDB;

CREATE OR REPLACE VIEW v_capture_16_bands AS
SELECT
  cg.id AS capture_group_id,
  cb.batch_code,
  sf.capture_date,
  cg.captured_at,
  lc.code AS light_code,
  cg.group_no,
  cg.first_plant_position,
  cg.last_plant_position,
  cg.mapping_status,
  sf.folder_name AS source_folder,
  COUNT(mi.id) AS band_file_count,
  MAX(CASE WHEN sb.wavelength_nm = 405 THEN mi.file_path END) AS L405,
  MAX(CASE WHEN sb.wavelength_nm = 430 THEN mi.file_path END) AS L430,
  MAX(CASE WHEN sb.wavelength_nm = 450 THEN mi.file_path END) AS L450,
  MAX(CASE WHEN sb.wavelength_nm = 475 THEN mi.file_path END) AS L475,
  MAX(CASE WHEN sb.wavelength_nm = 500 THEN mi.file_path END) AS L500,
  MAX(CASE WHEN sb.wavelength_nm = 540 THEN mi.file_path END) AS L540,
  MAX(CASE WHEN sb.wavelength_nm = 600 THEN mi.file_path END) AS L600,
  MAX(CASE WHEN sb.wavelength_nm = 630 THEN mi.file_path END) AS L630,
  MAX(CASE WHEN sb.wavelength_nm = 680 THEN mi.file_path END) AS L680,
  MAX(CASE WHEN sb.wavelength_nm = 700 THEN mi.file_path END) AS L700,
  MAX(CASE WHEN sb.wavelength_nm = 730 THEN mi.file_path END) AS L730,
  MAX(CASE WHEN sb.wavelength_nm = 770 THEN mi.file_path END) AS L770,
  MAX(CASE WHEN sb.wavelength_nm = 800 THEN mi.file_path END) AS L800,
  MAX(CASE WHEN sb.wavelength_nm = 850 THEN mi.file_path END) AS L850,
  MAX(CASE WHEN sb.wavelength_nm = 900 THEN mi.file_path END) AS L900,
  MAX(CASE WHEN sb.wavelength_nm = 980 THEN mi.file_path END) AS L980
FROM capture_groups AS cg
JOIN source_folders AS sf ON sf.id = cg.source_folder_id
JOIN crop_batches AS cb ON cb.id = sf.batch_id
LEFT JOIN light_conditions AS lc ON lc.id = cg.light_condition_id
LEFT JOIN multispectral_images AS mi ON mi.capture_group_id = cg.id
LEFT JOIN spectral_bands AS sb ON sb.id = mi.band_id
GROUP BY
  cg.id,
  cb.batch_code,
  sf.capture_date,
  cg.captured_at,
  lc.code,
  cg.group_no,
  cg.first_plant_position,
  cg.last_plant_position,
  cg.mapping_status,
  sf.folder_name;
