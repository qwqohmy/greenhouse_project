-- MySQL 8+. Independent database: plant_multispectral.
CREATE TABLE IF NOT EXISTS import_runs (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 snapshot_sha256 CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
 algorithm_version VARCHAR(64) NOT NULL,
 created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
 summary_json JSON NOT NULL
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS crop_batches (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 crop_code VARCHAR(32) NOT NULL,
 batch_no INT UNSIGNED NOT NULL,
 batch_code VARCHAR(64) NOT NULL UNIQUE,
 display_name VARCHAR(100) NOT NULL,
 first_captured_on DATE NOT NULL,
 last_captured_on DATE NOT NULL,
 plants_per_light INT UNSIGNED NULL,
 source_basis VARCHAR(100) NOT NULL,
 UNIQUE KEY uq_crop_batch (crop_code,batch_no)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS light_conditions (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 code VARCHAR(8) NOT NULL UNIQUE,
 rack_code CHAR(1) NOT NULL,
 level_no INT UNSIGNED NOT NULL,
 display_order INT UNSIGNED NOT NULL UNIQUE
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS spectral_bands (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 code VARCHAR(8) NOT NULL UNIQUE,
 wavelength_nm INT UNSIGNED NOT NULL UNIQUE,
 display_order INT UNSIGNED NOT NULL UNIQUE
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS source_folders (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 batch_id INT UNSIGNED NOT NULL,
 folder_name VARCHAR(255) NOT NULL,
 folder_path VARCHAR(1024) NOT NULL,
 source_path_hash CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
 original_source_exists BOOLEAN NOT NULL,
 FOREIGN KEY (batch_id) REFERENCES crop_batches(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS capture_groups (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 source_folder_id BIGINT UNSIGNED NOT NULL,
 light_condition_id INT UNSIGNED NOT NULL,
 captured_at DATETIME NOT NULL,
 capture_code VARCHAR(32) NOT NULL,
 shoot_no INT UNSIGNED NULL,
 photo_no INT UNSIGNED NULL,
 layout_code VARCHAR(100) NULL,
 segmentation_channel VARCHAR(32) NULL,
 sam_metadata_path VARCHAR(1024) NOT NULL,
 overview_image_path VARCHAR(1024) NULL,
 sam_metadata_sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
 metadata_json JSON NOT NULL,
 import_run_id BIGINT UNSIGNED NOT NULL,
 UNIQUE KEY uq_capture (source_folder_id,light_condition_id,captured_at),
 FOREIGN KEY (source_folder_id) REFERENCES source_folders(id),
 FOREIGN KEY (light_condition_id) REFERENCES light_conditions(id),
 FOREIGN KEY (import_run_id) REFERENCES import_runs(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS plants (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 batch_id INT UNSIGNED NOT NULL,
 light_condition_id INT UNSIGNED NOT NULL,
 position_no INT UNSIGNED NOT NULL,
 identity_status VARCHAR(64) NOT NULL DEFAULT 'SAM_LAYOUT_NUMBER',
 UNIQUE KEY uq_plant (batch_id,light_condition_id,position_no),
 CHECK(position_no>0),
 FOREIGN KEY (batch_id) REFERENCES crop_batches(id),
 FOREIGN KEY (light_condition_id) REFERENCES light_conditions(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS plant_observations (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 capture_group_id BIGINT UNSIGNED NOT NULL,
 plant_id BIGINT UNSIGNED NOT NULL,
 output_directory VARCHAR(1024) NOT NULL,
 directory_hash CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
 quality_status VARCHAR(64) NOT NULL,
 mask_source VARCHAR(64) NULL,
 mask_area_pixels BIGINT UNSIGNED NOT NULL,
 crop_box_json JSON NOT NULL,
 band_count INT UNSIGNED NOT NULL,
 import_run_id BIGINT UNSIGNED NOT NULL,
 UNIQUE KEY uq_observation (capture_group_id,plant_id),
 FOREIGN KEY (capture_group_id) REFERENCES capture_groups(id),
 FOREIGN KEY (plant_id) REFERENCES plants(id),
 FOREIGN KEY (import_run_id) REFERENCES import_runs(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS singleplant_images (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 observation_id BIGINT UNSIGNED NOT NULL,
 band_id INT UNSIGNED NULL,
 channel_code VARCHAR(64) NOT NULL,
 image_kind VARCHAR(32) NOT NULL,
 file_path VARCHAR(1024) NOT NULL,
 file_path_hash CHAR(64) CHARACTER SET ascii NOT NULL UNIQUE,
 file_size_bytes BIGINT UNSIGNED NOT NULL,
 file_modified_ns BIGINT UNSIGNED NOT NULL,
 content_sha256 CHAR(64) CHARACTER SET ascii NULL,
 original_file_path VARCHAR(1024) NULL,
 width_px INT UNSIGNED NOT NULL,
 height_px INT UNSIGNED NOT NULL,
 pixel_mode VARCHAR(24) NOT NULL,
 UNIQUE KEY uq_channel (observation_id,channel_code),
 FOREIGN KEY (observation_id) REFERENCES plant_observations(id),
 FOREIGN KEY (band_id) REFERENCES spectral_bands(id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS index_definitions (
 id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 code VARCHAR(32) NOT NULL,
 algorithm_version VARCHAR(64) NOT NULL,
 formula_text VARCHAR(255) NOT NULL,
 pixel_aggregation VARCHAR(128) NOT NULL,
 value_basis VARCHAR(64) NOT NULL,
 calibration_status VARCHAR(64) NOT NULL,
 alignment_status VARCHAR(100) NOT NULL,
 reference_url VARCHAR(512) NOT NULL,
 UNIQUE KEY uq_index (code,algorithm_version)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS index_measurements (
 id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
 observation_id BIGINT UNSIGNED NOT NULL,
 definition_id INT UNSIGNED NOT NULL,
 calculation_status VARCHAR(64) NOT NULL,
 index_mean DOUBLE NULL,
 index_median DOUBLE NULL,
 index_std DOUBLE NULL,
 index_min DOUBLE NULL,
 index_max DOUBLE NULL,
 index_p10 DOUBLE NULL,
 index_p90 DOUBLE NULL,
 red_mean_dn DOUBLE NULL,
 nir_mean_dn DOUBLE NULL,
 valid_pixel_count BIGINT UNSIGNED NOT NULL,
 mask_pixel_count BIGINT UNSIGNED NOT NULL,
 zero_denominator_count BIGINT UNSIGNED NOT NULL,
 saturated_pixel_count BIGINT UNSIGNED NOT NULL,
 input_sha256_json JSON NOT NULL,
 import_run_id BIGINT UNSIGNED NOT NULL,
 UNIQUE KEY uq_measurement (observation_id,definition_id),
 CHECK(index_mean IS NULL OR index_mean BETWEEN -1.000000001 AND 1.000000001),
 FOREIGN KEY (observation_id) REFERENCES plant_observations(id),
 FOREIGN KEY (definition_id) REFERENCES index_definitions(id),
 FOREIGN KEY (import_run_id) REFERENCES import_runs(id)
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW v_singleplant_16_bands AS
SELECT o.id AS observation_id,b.crop_code,b.batch_no,b.display_name AS batch_name,
 b.batch_code,l.code AS light_code,l.display_order AS light_order,
 DATE(c.captured_at) AS capture_date,c.captured_at,c.capture_code,
 p.position_no AS plant_number,p.identity_status,s.folder_name AS source_folder,
 o.output_directory,o.quality_status,o.mask_source,o.mask_area_pixels,o.band_count,
 MAX(CASE WHEN i.channel_code='L405' THEN i.file_path END) AS L405,
 MAX(CASE WHEN i.channel_code='L430' THEN i.file_path END) AS L430,
 MAX(CASE WHEN i.channel_code='L450' THEN i.file_path END) AS L450,
 MAX(CASE WHEN i.channel_code='L475' THEN i.file_path END) AS L475,
 MAX(CASE WHEN i.channel_code='L500' THEN i.file_path END) AS L500,
 MAX(CASE WHEN i.channel_code='L540' THEN i.file_path END) AS L540,
 MAX(CASE WHEN i.channel_code='L600' THEN i.file_path END) AS L600,
 MAX(CASE WHEN i.channel_code='L630' THEN i.file_path END) AS L630,
 MAX(CASE WHEN i.channel_code='L680' THEN i.file_path END) AS L680,
 MAX(CASE WHEN i.channel_code='L700' THEN i.file_path END) AS L700,
 MAX(CASE WHEN i.channel_code='L730' THEN i.file_path END) AS L730,
 MAX(CASE WHEN i.channel_code='L770' THEN i.file_path END) AS L770,
 MAX(CASE WHEN i.channel_code='L800' THEN i.file_path END) AS L800,
 MAX(CASE WHEN i.channel_code='L850' THEN i.file_path END) AS L850,
 MAX(CASE WHEN i.channel_code='L900' THEN i.file_path END) AS L900,
 MAX(CASE WHEN i.channel_code='L980' THEN i.file_path END) AS L980,
 MAX(CASE WHEN i.channel_code='mask' THEN i.file_path END) AS mask_path,
 MAX(CASE WHEN i.channel_code='Color' THEN i.file_path END) AS color_path,
 MAX(CASE WHEN i.channel_code='LNDVI' THEN i.file_path END) AS vendor_ndvi_image,
 m.index_mean AS ndvi_mean,m.index_median AS ndvi_median,m.index_std AS ndvi_std,
 m.index_min AS ndvi_min,m.index_max AS ndvi_max,m.valid_pixel_count,
 m.calculation_status AS ndvi_status,d.value_basis AS ndvi_value_basis,
 d.calibration_status,d.alignment_status,d.algorithm_version AS ndvi_algorithm
FROM plant_observations o
JOIN plants p ON p.id=o.plant_id JOIN crop_batches b ON b.id=p.batch_id
JOIN light_conditions l ON l.id=p.light_condition_id
JOIN capture_groups c ON c.id=o.capture_group_id
JOIN source_folders s ON s.id=c.source_folder_id
LEFT JOIN singleplant_images i ON i.observation_id=o.id
LEFT JOIN index_definitions d ON d.code='NDVI' AND d.algorithm_version='ndvi800680_dn_v1'
LEFT JOIN index_measurements m ON m.observation_id=o.id AND m.definition_id=d.id
GROUP BY o.id,b.id,l.id,p.id,c.id,s.id,m.id,d.id;

CREATE OR REPLACE VIEW v_batch_summary AS
SELECT b.id AS batch_id,b.crop_code,b.batch_no,b.display_name,b.batch_code,
 b.plants_per_light,b.first_captured_on,b.last_captured_on,
 COUNT(DISTINCT p.id) AS plant_numbers_recorded,
 COUNT(DISTINCT o.id) AS plant_observations,
 COUNT(DISTINCT o.capture_group_id) AS capture_groups
FROM crop_batches b LEFT JOIN plants p ON p.batch_id=b.id
LEFT JOIN plant_observations o ON o.plant_id=p.id GROUP BY b.id;
