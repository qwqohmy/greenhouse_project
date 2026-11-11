SET FOREIGN_KEY_CHECKS=0;
CREATE TABLE `capture_groups` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `source_folder_id` bigint unsigned NOT NULL,
  `light_condition_id` int unsigned NOT NULL,
  `captured_at` datetime NOT NULL,
  `capture_code` varchar(32) NOT NULL,
  `shoot_no` int unsigned DEFAULT NULL,
  `photo_no` int unsigned DEFAULT NULL,
  `layout_code` varchar(100) DEFAULT NULL,
  `segmentation_channel` varchar(32) DEFAULT NULL,
  `sam_metadata_path` varchar(1024) NOT NULL,
  `overview_image_path` varchar(1024) DEFAULT NULL,
  `sam_metadata_sha256` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `metadata_json` json NOT NULL,
  `import_run_id` bigint unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_capture` (`source_folder_id`,`light_condition_id`,`captured_at`),
  KEY `light_condition_id` (`light_condition_id`),
  KEY `import_run_id` (`import_run_id`),
  CONSTRAINT `capture_groups_ibfk_1` FOREIGN KEY (`source_folder_id`) REFERENCES `source_folders` (`id`),
  CONSTRAINT `capture_groups_ibfk_2` FOREIGN KEY (`light_condition_id`) REFERENCES `light_conditions` (`id`),
  CONSTRAINT `capture_groups_ibfk_3` FOREIGN KEY (`import_run_id`) REFERENCES `import_runs` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=1157 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `crop_batches` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `crop_code` varchar(32) NOT NULL,
  `batch_no` int unsigned NOT NULL,
  `batch_code` varchar(64) NOT NULL,
  `display_name` varchar(100) NOT NULL,
  `first_captured_on` date NOT NULL,
  `last_captured_on` date NOT NULL,
  `plants_per_light` int unsigned DEFAULT NULL,
  `source_basis` varchar(100) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `batch_code` (`batch_code`),
  UNIQUE KEY `uq_crop_batch` (`crop_code`,`batch_no`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `import_runs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `snapshot_sha256` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `algorithm_version` varchar(64) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `summary_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `snapshot_sha256` (`snapshot_sha256`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `index_definitions` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `code` varchar(32) NOT NULL,
  `algorithm_version` varchar(64) NOT NULL,
  `formula_text` varchar(255) NOT NULL,
  `pixel_aggregation` varchar(128) NOT NULL,
  `value_basis` varchar(64) NOT NULL,
  `calibration_status` varchar(64) NOT NULL,
  `alignment_status` varchar(100) NOT NULL,
  `reference_url` varchar(512) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_index` (`code`,`algorithm_version`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `index_measurements` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `observation_id` bigint unsigned NOT NULL,
  `definition_id` int unsigned NOT NULL,
  `calculation_status` varchar(64) NOT NULL,
  `index_mean` double DEFAULT NULL,
  `index_median` double DEFAULT NULL,
  `index_std` double DEFAULT NULL,
  `index_min` double DEFAULT NULL,
  `index_max` double DEFAULT NULL,
  `index_p10` double DEFAULT NULL,
  `index_p90` double DEFAULT NULL,
  `red_mean_dn` double DEFAULT NULL,
  `nir_mean_dn` double DEFAULT NULL,
  `valid_pixel_count` bigint unsigned NOT NULL,
  `mask_pixel_count` bigint unsigned NOT NULL,
  `zero_denominator_count` bigint unsigned NOT NULL,
  `saturated_pixel_count` bigint unsigned NOT NULL,
  `input_sha256_json` json NOT NULL,
  `import_run_id` bigint unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_measurement` (`observation_id`,`definition_id`),
  KEY `definition_id` (`definition_id`),
  KEY `import_run_id` (`import_run_id`),
  CONSTRAINT `index_measurements_ibfk_1` FOREIGN KEY (`observation_id`) REFERENCES `plant_observations` (`id`),
  CONSTRAINT `index_measurements_ibfk_2` FOREIGN KEY (`definition_id`) REFERENCES `index_definitions` (`id`),
  CONSTRAINT `index_measurements_ibfk_3` FOREIGN KEY (`import_run_id`) REFERENCES `import_runs` (`id`),
  CONSTRAINT `index_measurements_chk_1` CHECK (((`index_mean` is null) or (`index_mean` between -(1.000000001) and 1.000000001)))
) ENGINE=InnoDB AUTO_INCREMENT=5941 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `light_conditions` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `code` varchar(8) NOT NULL,
  `rack_code` char(1) NOT NULL,
  `level_no` int unsigned NOT NULL,
  `display_order` int unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  UNIQUE KEY `display_order` (`display_order`)
) ENGINE=InnoDB AUTO_INCREMENT=13 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `plant_observations` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `capture_group_id` bigint unsigned NOT NULL,
  `plant_id` bigint unsigned NOT NULL,
  `output_directory` varchar(1024) NOT NULL,
  `directory_hash` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `quality_status` varchar(64) NOT NULL,
  `mask_source` varchar(64) DEFAULT NULL,
  `mask_area_pixels` bigint unsigned NOT NULL,
  `crop_box_json` json NOT NULL,
  `band_count` int unsigned NOT NULL,
  `import_run_id` bigint unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `directory_hash` (`directory_hash`),
  UNIQUE KEY `uq_observation` (`capture_group_id`,`plant_id`),
  KEY `plant_id` (`plant_id`),
  KEY `import_run_id` (`import_run_id`),
  CONSTRAINT `plant_observations_ibfk_1` FOREIGN KEY (`capture_group_id`) REFERENCES `capture_groups` (`id`),
  CONSTRAINT `plant_observations_ibfk_2` FOREIGN KEY (`plant_id`) REFERENCES `plants` (`id`),
  CONSTRAINT `plant_observations_ibfk_3` FOREIGN KEY (`import_run_id`) REFERENCES `import_runs` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=5941 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `plants` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `batch_id` int unsigned NOT NULL,
  `light_condition_id` int unsigned NOT NULL,
  `position_no` int unsigned NOT NULL,
  `identity_status` varchar(64) NOT NULL DEFAULT 'SAM_LAYOUT_NUMBER',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_plant` (`batch_id`,`light_condition_id`,`position_no`),
  KEY `light_condition_id` (`light_condition_id`),
  CONSTRAINT `plants_ibfk_1` FOREIGN KEY (`batch_id`) REFERENCES `crop_batches` (`id`),
  CONSTRAINT `plants_ibfk_2` FOREIGN KEY (`light_condition_id`) REFERENCES `light_conditions` (`id`),
  CONSTRAINT `plants_chk_1` CHECK ((`position_no` > 0))
) ENGINE=InnoDB AUTO_INCREMENT=397 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `singleplant_images` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `observation_id` bigint unsigned NOT NULL,
  `band_id` int unsigned DEFAULT NULL,
  `channel_code` varchar(64) NOT NULL,
  `image_kind` varchar(32) NOT NULL,
  `file_path` varchar(1024) NOT NULL,
  `file_path_hash` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `file_size_bytes` bigint unsigned NOT NULL,
  `file_modified_ns` bigint unsigned NOT NULL,
  `content_sha256` char(64) CHARACTER SET ascii COLLATE ascii_general_ci DEFAULT NULL,
  `original_file_path` varchar(1024) DEFAULT NULL,
  `width_px` int unsigned NOT NULL,
  `height_px` int unsigned NOT NULL,
  `pixel_mode` varchar(24) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `file_path_hash` (`file_path_hash`),
  UNIQUE KEY `uq_channel` (`observation_id`,`channel_code`),
  KEY `band_id` (`band_id`),
  CONSTRAINT `singleplant_images_ibfk_1` FOREIGN KEY (`observation_id`) REFERENCES `plant_observations` (`id`),
  CONSTRAINT `singleplant_images_ibfk_2` FOREIGN KEY (`band_id`) REFERENCES `spectral_bands` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=106270 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `source_folders` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `batch_id` int unsigned NOT NULL,
  `folder_name` varchar(255) NOT NULL,
  `folder_path` varchar(1024) NOT NULL,
  `source_path_hash` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `original_source_exists` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `source_path_hash` (`source_path_hash`),
  KEY `batch_id` (`batch_id`),
  CONSTRAINT `source_folders_ibfk_1` FOREIGN KEY (`batch_id`) REFERENCES `crop_batches` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=121 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `spectral_bands` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `code` varchar(8) NOT NULL,
  `wavelength_nm` int unsigned NOT NULL,
  `display_order` int unsigned NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `code` (`code`),
  UNIQUE KEY `wavelength_nm` (`wavelength_nm`),
  UNIQUE KEY `display_order` (`display_order`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE ALGORITHM=UNDEFINED SQL SECURITY INVOKER VIEW `v_batch_summary` AS select `b`.`id` AS `batch_id`,`b`.`crop_code` AS `crop_code`,`b`.`batch_no` AS `batch_no`,`b`.`display_name` AS `display_name`,`b`.`batch_code` AS `batch_code`,`b`.`plants_per_light` AS `plants_per_light`,`b`.`first_captured_on` AS `first_captured_on`,`b`.`last_captured_on` AS `last_captured_on`,count(distinct `p`.`id`) AS `plant_numbers_recorded`,count(distinct `o`.`id`) AS `plant_observations`,count(distinct `o`.`capture_group_id`) AS `capture_groups` from ((`crop_batches` `b` left join `plants` `p` on((`p`.`batch_id` = `b`.`id`))) left join `plant_observations` `o` on((`o`.`plant_id` = `p`.`id`))) group by `b`.`id`;
CREATE ALGORITHM=UNDEFINED SQL SECURITY INVOKER VIEW `v_singleplant_16_bands` AS select `o`.`id` AS `observation_id`,`b`.`crop_code` AS `crop_code`,`b`.`batch_no` AS `batch_no`,`b`.`display_name` AS `batch_name`,`b`.`batch_code` AS `batch_code`,`l`.`code` AS `light_code`,`l`.`display_order` AS `light_order`,cast(`c`.`captured_at` as date) AS `capture_date`,`c`.`captured_at` AS `captured_at`,`c`.`capture_code` AS `capture_code`,`p`.`position_no` AS `plant_number`,`p`.`identity_status` AS `identity_status`,`s`.`folder_name` AS `source_folder`,`o`.`output_directory` AS `output_directory`,`o`.`quality_status` AS `quality_status`,`o`.`mask_source` AS `mask_source`,`o`.`mask_area_pixels` AS `mask_area_pixels`,`o`.`band_count` AS `band_count`,max((case when (`i`.`channel_code` = 'L405') then `i`.`file_path` end)) AS `L405`,max((case when (`i`.`channel_code` = 'L430') then `i`.`file_path` end)) AS `L430`,max((case when (`i`.`channel_code` = 'L450') then `i`.`file_path` end)) AS `L450`,max((case when (`i`.`channel_code` = 'L475') then `i`.`file_path` end)) AS `L475`,max((case when (`i`.`channel_code` = 'L500') then `i`.`file_path` end)) AS `L500`,max((case when (`i`.`channel_code` = 'L540') then `i`.`file_path` end)) AS `L540`,max((case when (`i`.`channel_code` = 'L600') then `i`.`file_path` end)) AS `L600`,max((case when (`i`.`channel_code` = 'L630') then `i`.`file_path` end)) AS `L630`,max((case when (`i`.`channel_code` = 'L680') then `i`.`file_path` end)) AS `L680`,max((case when (`i`.`channel_code` = 'L700') then `i`.`file_path` end)) AS `L700`,max((case when (`i`.`channel_code` = 'L730') then `i`.`file_path` end)) AS `L730`,max((case when (`i`.`channel_code` = 'L770') then `i`.`file_path` end)) AS `L770`,max((case when (`i`.`channel_code` = 'L800') then `i`.`file_path` end)) AS `L800`,max((case when (`i`.`channel_code` = 'L850') then `i`.`file_path` end)) AS `L850`,max((case when (`i`.`channel_code` = 'L900') then `i`.`file_path` end)) AS `L900`,max((case when (`i`.`channel_code` = 'L980') then `i`.`file_path` end)) AS `L980`,max((case when (`i`.`channel_code` = 'mask') then `i`.`file_path` end)) AS `mask_path`,max((case when (`i`.`channel_code` = 'Color') then `i`.`file_path` end)) AS `color_path`,max((case when (`i`.`channel_code` = 'LNDVI') then `i`.`file_path` end)) AS `vendor_ndvi_image`,`m`.`index_mean` AS `ndvi_mean`,`m`.`index_median` AS `ndvi_median`,`m`.`index_std` AS `ndvi_std`,`m`.`index_min` AS `ndvi_min`,`m`.`index_max` AS `ndvi_max`,`m`.`valid_pixel_count` AS `valid_pixel_count`,`m`.`calculation_status` AS `ndvi_status`,`d`.`value_basis` AS `ndvi_value_basis`,`d`.`calibration_status` AS `calibration_status`,`d`.`alignment_status` AS `alignment_status`,`d`.`algorithm_version` AS `ndvi_algorithm` from ((((((((`plant_observations` `o` join `plants` `p` on((`p`.`id` = `o`.`plant_id`))) join `crop_batches` `b` on((`b`.`id` = `p`.`batch_id`))) join `light_conditions` `l` on((`l`.`id` = `p`.`light_condition_id`))) join `capture_groups` `c` on((`c`.`id` = `o`.`capture_group_id`))) join `source_folders` `s` on((`s`.`id` = `c`.`source_folder_id`))) left join `singleplant_images` `i` on((`i`.`observation_id` = `o`.`id`))) left join `index_definitions` `d` on(((`d`.`code` = 'NDVI') and (`d`.`algorithm_version` = 'ndvi800680_dn_v1')))) left join `index_measurements` `m` on(((`m`.`observation_id` = `o`.`id`) and (`m`.`definition_id` = `d`.`id`)))) group by `o`.`id`,`b`.`id`,`l`.`id`,`p`.`id`,`c`.`id`,`s`.`id`,`m`.`id`,`d`.`id`;
SET FOREIGN_KEY_CHECKS=1;
