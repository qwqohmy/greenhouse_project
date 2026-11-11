SET FOREIGN_KEY_CHECKS=0;
CREATE TABLE `p3d_assets` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `host_id` smallint unsigned NOT NULL,
  `path_sha256` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `file_path` text NOT NULL,
  `asset_kind` varchar(32) NOT NULL,
  `content_sha256` char(64) CHARACTER SET ascii COLLATE ascii_general_ci DEFAULT NULL,
  `file_size_bytes` bigint unsigned DEFAULT NULL,
  `exists_on_export` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_p3d_asset_path` (`host_id`,`path_sha256`),
  KEY `ix_p3d_asset_content` (`content_sha256`),
  CONSTRAINT `p3d_assets_ibfk_1` FOREIGN KEY (`host_id`) REFERENCES `p3d_hosts` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=387145 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_batches` (
  `id` smallint unsigned NOT NULL AUTO_INCREMENT,
  `batch_code` varchar(64) NOT NULL,
  `crop` varchar(24) NOT NULL,
  `plants_per_light` smallint unsigned DEFAULT NULL,
  `light_count` smallint unsigned DEFAULT NULL,
  `evidence` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `batch_code` (`batch_code`)
) ENGINE=InnoDB AUTO_INCREMENT=16 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_components` (
  `component_code` varchar(80) NOT NULL,
  `purpose` varchar(100) NOT NULL,
  `license_name` varchar(100) NOT NULL,
  `code_license_verified` tinyint(1) NOT NULL,
  `weights_license_verified` tinyint(1) NOT NULL,
  `strict_open_source_status` varchar(64) NOT NULL,
  `source_url` text NOT NULL,
  `notes` text,
  PRIMARY KEY (`component_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_csv_exports` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `export_key` varchar(100) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `csv_asset_id` bigint unsigned NOT NULL,
  `source_ply_asset_id` bigint unsigned NOT NULL,
  `geometry_asset_id` bigint unsigned NOT NULL,
  `point_indices_asset_id` bigint unsigned NOT NULL,
  `metadata_asset_id` bigint unsigned NOT NULL,
  `export_kind` varchar(32) NOT NULL,
  `algorithm_version` varchar(100) NOT NULL,
  `coordinate_unit` varchar(64) NOT NULL,
  `source_scope_status` varchar(100) DEFAULT NULL,
  `raw_values_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `export_key` (`export_key`),
  UNIQUE KEY `csv_asset_id` (`csv_asset_id`),
  KEY `source_ply_asset_id` (`source_ply_asset_id`),
  KEY `geometry_asset_id` (`geometry_asset_id`),
  KEY `point_indices_asset_id` (`point_indices_asset_id`),
  KEY `metadata_asset_id` (`metadata_asset_id`),
  CONSTRAINT `p3d_csv_exports_ibfk_1` FOREIGN KEY (`csv_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_csv_exports_ibfk_2` FOREIGN KEY (`source_ply_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_csv_exports_ibfk_3` FOREIGN KEY (`geometry_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_csv_exports_ibfk_4` FOREIGN KEY (`point_indices_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_csv_exports_ibfk_5` FOREIGN KEY (`metadata_asset_id`) REFERENCES `p3d_assets` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=793 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_hosts` (
  `id` smallint unsigned NOT NULL AUTO_INCREMENT,
  `host_code` varchar(64) NOT NULL,
  `description` varchar(255) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `host_code` (`host_code`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_images` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `asset_id` bigint unsigned NOT NULL,
  `session_id` bigint unsigned NOT NULL,
  `source_image_asset_id` bigint unsigned DEFAULT NULL,
  `mask_asset_id` bigint unsigned DEFAULT NULL,
  `segmented_asset_id` bigint unsigned DEFAULT NULL,
  `metadata_asset_id` bigint unsigned DEFAULT NULL,
  `image_kind` varchar(12) NOT NULL,
  `camera_code` varchar(12) NOT NULL,
  `frame_index` int unsigned NOT NULL,
  `instance_local_id` int unsigned DEFAULT NULL,
  `algorithm_version` varchar(64) DEFAULT NULL,
  `quality_status` varchar(64) NOT NULL,
  `source_bbox_json` json DEFAULT NULL,
  `source_edge_truncated` tinyint(1) NOT NULL DEFAULT '0',
  PRIMARY KEY (`id`),
  UNIQUE KEY `asset_id` (`asset_id`),
  KEY `source_image_asset_id` (`source_image_asset_id`),
  KEY `mask_asset_id` (`mask_asset_id`),
  KEY `segmented_asset_id` (`segmented_asset_id`),
  KEY `metadata_asset_id` (`metadata_asset_id`),
  KEY `ix_p3d_image_session` (`session_id`,`camera_code`,`frame_index`),
  CONSTRAINT `p3d_images_ibfk_1` FOREIGN KEY (`asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_images_ibfk_2` FOREIGN KEY (`session_id`) REFERENCES `p3d_sessions` (`id`),
  CONSTRAINT `p3d_images_ibfk_3` FOREIGN KEY (`source_image_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_images_ibfk_4` FOREIGN KEY (`mask_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_images_ibfk_5` FOREIGN KEY (`segmented_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_images_ibfk_6` FOREIGN KEY (`metadata_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_images_chk_1` CHECK ((`image_kind` in (_utf8mb4'RAW',_utf8mb4'CROP')))
) ENGINE=InnoDB AUTO_INCREMENT=157859 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_import_runs` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `snapshot_sha256` char(64) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `imported_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `source_host` varchar(64) NOT NULL,
  `summary_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `snapshot_sha256` (`snapshot_sha256`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_measurements` (
  `csv_export_id` bigint unsigned NOT NULL,
  `metric_code` varchar(80) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `metric_value` double DEFAULT NULL,
  `unit` varchar(64) DEFAULT NULL,
  `measurement_kind` varchar(24) NOT NULL,
  PRIMARY KEY (`csv_export_id`,`metric_code`),
  CONSTRAINT `p3d_measurements_ibfk_1` FOREIGN KEY (`csv_export_id`) REFERENCES `p3d_csv_exports` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_observation_images` (
  `observation_id` bigint unsigned NOT NULL,
  `image_id` bigint unsigned NOT NULL,
  `link_status` varchar(32) NOT NULL,
  `link_evidence_json` json NOT NULL,
  PRIMARY KEY (`observation_id`,`image_id`),
  KEY `image_id` (`image_id`),
  CONSTRAINT `p3d_observation_images_ibfk_1` FOREIGN KEY (`observation_id`) REFERENCES `p3d_observations` (`id`),
  CONSTRAINT `p3d_observation_images_ibfk_2` FOREIGN KEY (`image_id`) REFERENCES `p3d_images` (`id`),
  CONSTRAINT `p3d_observation_images_chk_1` CHECK ((`link_status` in (_utf8mb4'CANDIDATE',_utf8mb4'LINKED_SCENE',_utf8mb4'VERIFIED',_utf8mb4'REJECTED')))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_observations` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `observation_key` varchar(100) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `ply_session_id` bigint unsigned NOT NULL,
  `target_csv_export_id` bigint unsigned NOT NULL,
  `component_index` int unsigned NOT NULL,
  `scene_local_plant_id` varchar(100) CHARACTER SET ascii COLLATE ascii_general_ci DEFAULT NULL,
  `physical_plant_id` varchar(100) DEFAULT NULL,
  `physical_plant_id_candidate` varchar(100) DEFAULT NULL,
  `visual_review_status` varchar(100) NOT NULL,
  `geometry_scope_verified` tinyint(1) NOT NULL DEFAULT '0',
  `rgb_identity_verified` tinyint(1) NOT NULL DEFAULT '0',
  `input_crop_complete_verified` tinyint(1) NOT NULL DEFAULT '0',
  `coordinate_units_verified` tinyint(1) NOT NULL DEFAULT '0',
  `target_definitions_verified` tinyint(1) NOT NULL DEFAULT '0',
  `numeric_provenance_verified` tinyint(1) NOT NULL DEFAULT '0',
  `averaged_across_plants` tinyint(1) NOT NULL DEFAULT '0',
  `review_notes` text,
  `evidence_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `observation_key` (`observation_key`),
  UNIQUE KEY `target_csv_export_id` (`target_csv_export_id`),
  KEY `ply_session_id` (`ply_session_id`),
  CONSTRAINT `p3d_observations_ibfk_1` FOREIGN KEY (`ply_session_id`) REFERENCES `p3d_sessions` (`id`),
  CONSTRAINT `p3d_observations_ibfk_2` FOREIGN KEY (`target_csv_export_id`) REFERENCES `p3d_csv_exports` (`id`),
  CONSTRAINT `p3d_observations_chk_1` CHECK ((`averaged_across_plants` = false))
) ENGINE=InnoDB AUTO_INCREMENT=532 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_processing_runs` (
  `run_key` varchar(100) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `capture_set` varchar(64) NOT NULL,
  `run_status` varchar(64) NOT NULL,
  `total_images` int unsigned NOT NULL,
  `processed_images` int unsigned NOT NULL,
  `detected_instances` int unsigned NOT NULL,
  `no_detection_images` int unsigned NOT NULL,
  `error_count` int unsigned NOT NULL,
  PRIMARY KEY (`run_key`),
  CONSTRAINT `p3d_processing_runs_chk_1` CHECK ((`processed_images` <= `total_images`))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_segmentation_results` (
  `source_image_asset_id` bigint unsigned NOT NULL,
  `metadata_asset_id` bigint unsigned NOT NULL,
  `algorithm_version` varchar(64) NOT NULL,
  `result_status` varchar(64) NOT NULL,
  `instance_count` int unsigned NOT NULL,
  `details_json` json NOT NULL,
  PRIMARY KEY (`source_image_asset_id`),
  KEY `metadata_asset_id` (`metadata_asset_id`),
  CONSTRAINT `p3d_segmentation_results_ibfk_1` FOREIGN KEY (`source_image_asset_id`) REFERENCES `p3d_assets` (`id`),
  CONSTRAINT `p3d_segmentation_results_ibfk_2` FOREIGN KEY (`metadata_asset_id`) REFERENCES `p3d_assets` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_session_candidates` (
  `observation_id` bigint unsigned NOT NULL,
  `rgb_session_id` bigint unsigned NOT NULL,
  `delta_seconds` double NOT NULL,
  `match_status` varchar(64) NOT NULL,
  `evidence_json` json DEFAULT NULL,
  PRIMARY KEY (`observation_id`,`rgb_session_id`),
  KEY `rgb_session_id` (`rgb_session_id`),
  CONSTRAINT `p3d_session_candidates_ibfk_1` FOREIGN KEY (`observation_id`) REFERENCES `p3d_observations` (`id`),
  CONSTRAINT `p3d_session_candidates_ibfk_2` FOREIGN KEY (`rgb_session_id`) REFERENCES `p3d_sessions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_sessions` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `session_key` varchar(191) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `session_kind` varchar(16) NOT NULL,
  `source_host_id` smallint unsigned NOT NULL,
  `batch_id` smallint unsigned DEFAULT NULL,
  `capture_code` varchar(32) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `captured_at` datetime NOT NULL,
  `crop` varchar(24) NOT NULL,
  `source_folder` text NOT NULL,
  `dataset_code` varchar(100) DEFAULT NULL,
  `expected_rgb_frames` int unsigned NOT NULL DEFAULT '0',
  `review_status` varchar(80) NOT NULL,
  `evidence_json` json DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `session_key` (`session_key`),
  KEY `source_host_id` (`source_host_id`),
  KEY `batch_id` (`batch_id`),
  KEY `ix_p3d_session_time` (`captured_at`,`crop`),
  CONSTRAINT `p3d_sessions_ibfk_1` FOREIGN KEY (`source_host_id`) REFERENCES `p3d_hosts` (`id`),
  CONSTRAINT `p3d_sessions_ibfk_2` FOREIGN KEY (`batch_id`) REFERENCES `p3d_batches` (`id`),
  CONSTRAINT `p3d_sessions_chk_1` CHECK ((`session_kind` in (_utf8mb4'RGB',_utf8mb4'PLY')))
) ENGINE=InnoDB AUTO_INCREMENT=625 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_user_sample_images` (
  `sample_id` bigint unsigned NOT NULL,
  `image_id` bigint unsigned NOT NULL,
  PRIMARY KEY (`sample_id`,`image_id`),
  UNIQUE KEY `image_id` (`image_id`),
  CONSTRAINT `p3d_user_sample_images_ibfk_1` FOREIGN KEY (`sample_id`) REFERENCES `p3d_user_samples` (`id`),
  CONSTRAINT `p3d_user_sample_images_ibfk_2` FOREIGN KEY (`image_id`) REFERENCES `p3d_images` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE `p3d_user_samples` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `sample_key` varchar(191) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `rgb_session_id` bigint unsigned NOT NULL,
  `crop` varchar(24) NOT NULL,
  `batch_code` varchar(64) NOT NULL,
  `capture_code` varchar(32) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `capture_date` date NOT NULL,
  `csv_capture_code` varchar(32) CHARACTER SET ascii COLLATE ascii_general_ci NOT NULL,
  `csv_minus_rgb_seconds` double NOT NULL,
  `confirmation_status` varchar(64) NOT NULL,
  `primary_csv_asset_id` bigint unsigned NOT NULL,
  `primary_kind` varchar(40) NOT NULL,
  `trial_eligible` tinyint(1) NOT NULL,
  `native_trial_eligible` tinyint(1) NOT NULL,
  `proxy_trial_eligible` tinyint(1) NOT NULL,
  `target_sources_json` json NOT NULL,
  `evidence_json` json NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `sample_key` (`sample_key`),
  UNIQUE KEY `rgb_session_id` (`rgb_session_id`),
  KEY `primary_csv_asset_id` (`primary_csv_asset_id`),
  CONSTRAINT `p3d_user_samples_ibfk_1` FOREIGN KEY (`rgb_session_id`) REFERENCES `p3d_sessions` (`id`),
  CONSTRAINT `p3d_user_samples_ibfk_2` FOREIGN KEY (`primary_csv_asset_id`) REFERENCES `p3d_assets` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=37 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE ALGORITHM=UNDEFINED SQL SECURITY INVOKER VIEW `p3d_v_image_csv_pairs` AS select `o`.`observation_key` AS `observation_key`,`s`.`captured_at` AS `captured_at`,`s`.`crop` AS `crop`,`o`.`scene_local_plant_id` AS `scene_local_plant_id`,`o`.`physical_plant_id` AS `physical_plant_id`,`o`.`physical_plant_id_candidate` AS `physical_plant_id_candidate`,`i`.`camera_code` AS `camera_code`,`i`.`frame_index` AS `frame_index`,`h`.`host_code` AS `image_host`,`a`.`file_path` AS `image_path`,`source`.`file_path` AS `original_image_path`,`mask`.`file_path` AS `mask_path`,`target`.`file_path` AS `csv_path`,`l`.`link_status` AS `link_status`,`i`.`quality_status` AS `quality_status`,`o`.`visual_review_status` AS `visual_review_status`,`e`.`coordinate_unit` AS `coordinate_unit`,`a`.`exists_on_export` AS `image_exists`,`mask`.`exists_on_export` AS `mask_exists`,`rgb_session`.`review_status` AS `image_session_review_status`,`rgb_session`.`crop` AS `image_session_crop` from ((((((((((`p3d_observation_images` `l` join `p3d_observations` `o` on((`o`.`id` = `l`.`observation_id`))) join `p3d_sessions` `s` on((`s`.`id` = `o`.`ply_session_id`))) join `p3d_images` `i` on((`i`.`id` = `l`.`image_id`))) join `p3d_sessions` `rgb_session` on((`rgb_session`.`id` = `i`.`session_id`))) join `p3d_assets` `a` on((`a`.`id` = `i`.`asset_id`))) join `p3d_hosts` `h` on((`h`.`id` = `a`.`host_id`))) left join `p3d_assets` `source` on((`source`.`id` = `i`.`source_image_asset_id`))) left join `p3d_assets` `mask` on((`mask`.`id` = `i`.`mask_asset_id`))) join `p3d_csv_exports` `e` on((`e`.`id` = `o`.`target_csv_export_id`))) join `p3d_assets` `target` on((`target`.`id` = `e`.`csv_asset_id`)));
CREATE ALGORITHM=UNDEFINED SQL SECURITY INVOKER VIEW `p3d_v_observations` AS select `o`.`id` AS `observation_id`,`o`.`observation_key` AS `observation_key`,`s`.`capture_code` AS `capture_code`,`s`.`captured_at` AS `captured_at`,`s`.`crop` AS `crop`,`b`.`batch_code` AS `batch_code`,`o`.`scene_local_plant_id` AS `scene_local_plant_id`,`o`.`physical_plant_id` AS `physical_plant_id`,`o`.`physical_plant_id_candidate` AS `physical_plant_id_candidate`,`h`.`host_code` AS `target_host`,`a`.`file_path` AS `csv_path`,`o`.`visual_review_status` AS `visual_review_status`,coalesce(`images`.`linked_images`,0) AS `linked_image_count`,coalesce(`images`.`verified_images`,0) AS `verified_image_count`,`metrics`.`pGH_proxy` AS `pGH_proxy`,`metrics`.`pMW_proxy` AS `pMW_proxy`,`metrics`.`xy_convex_hull_area` AS `xy_convex_hull_area`,`e`.`coordinate_unit` AS `coordinate_unit`,`o`.`geometry_scope_verified` AS `geometry_scope_verified`,`o`.`rgb_identity_verified` AS `rgb_identity_verified`,`o`.`input_crop_complete_verified` AS `input_crop_complete_verified`,`o`.`coordinate_units_verified` AS `coordinate_units_verified`,`o`.`target_definitions_verified` AS `target_definitions_verified`,`o`.`numeric_provenance_verified` AS `numeric_provenance_verified`,`o`.`averaged_across_plants` AS `averaged_across_plants`,`o`.`review_notes` AS `review_notes` from (((((((`p3d_observations` `o` join `p3d_sessions` `s` on((`s`.`id` = `o`.`ply_session_id`))) left join `p3d_batches` `b` on((`b`.`id` = `s`.`batch_id`))) join `p3d_csv_exports` `e` on((`e`.`id` = `o`.`target_csv_export_id`))) join `p3d_assets` `a` on((`a`.`id` = `e`.`csv_asset_id`))) join `p3d_hosts` `h` on((`h`.`id` = `a`.`host_id`))) left join (select `p3d_observation_images`.`observation_id` AS `observation_id`,sum((`p3d_observation_images`.`link_status` in ('LINKED_SCENE','VERIFIED'))) AS `linked_images`,sum((`p3d_observation_images`.`link_status` = 'VERIFIED')) AS `verified_images` from `p3d_observation_images` group by `p3d_observation_images`.`observation_id`) `images` on((`images`.`observation_id` = `o`.`id`))) left join (select `p3d_measurements`.`csv_export_id` AS `csv_export_id`,max((case when (`p3d_measurements`.`metric_code` = 'pGH_proxy') then `p3d_measurements`.`metric_value` end)) AS `pGH_proxy`,max((case when (`p3d_measurements`.`metric_code` = 'pMW_proxy') then `p3d_measurements`.`metric_value` end)) AS `pMW_proxy`,max((case when (`p3d_measurements`.`metric_code` = 'xy_convex_hull_area') then `p3d_measurements`.`metric_value` end)) AS `xy_convex_hull_area` from `p3d_measurements` group by `p3d_measurements`.`csv_export_id`) `metrics` on((`metrics`.`csv_export_id` = `e`.`id`)));
CREATE ALGORITHM=UNDEFINED SQL SECURITY INVOKER VIEW `p3d_v_training_ready` AS select `pairs`.`observation_key` AS `observation_key`,`pairs`.`captured_at` AS `captured_at`,`pairs`.`crop` AS `crop`,`pairs`.`scene_local_plant_id` AS `scene_local_plant_id`,`pairs`.`physical_plant_id` AS `physical_plant_id`,`pairs`.`physical_plant_id_candidate` AS `physical_plant_id_candidate`,`pairs`.`camera_code` AS `camera_code`,`pairs`.`frame_index` AS `frame_index`,`pairs`.`image_host` AS `image_host`,`pairs`.`image_path` AS `image_path`,`pairs`.`original_image_path` AS `original_image_path`,`pairs`.`mask_path` AS `mask_path`,`pairs`.`csv_path` AS `csv_path`,`pairs`.`link_status` AS `link_status`,`pairs`.`quality_status` AS `quality_status`,`pairs`.`visual_review_status` AS `visual_review_status`,`pairs`.`coordinate_unit` AS `coordinate_unit`,`pairs`.`image_exists` AS `image_exists`,`pairs`.`mask_exists` AS `mask_exists`,`pairs`.`image_session_review_status` AS `image_session_review_status`,`pairs`.`image_session_crop` AS `image_session_crop` from (((`p3d_v_image_csv_pairs` `pairs` join `p3d_observations` `o` on((`o`.`observation_key` = `pairs`.`observation_key`))) join `p3d_csv_exports` `e` on((`e`.`id` = `o`.`target_csv_export_id`))) join `p3d_assets` `target` on((`target`.`id` = `e`.`csv_asset_id`))) where ((`o`.`geometry_scope_verified` = true) and (`o`.`rgb_identity_verified` = true) and (`o`.`input_crop_complete_verified` = true) and (`o`.`coordinate_units_verified` = true) and (`o`.`target_definitions_verified` = true) and (`o`.`numeric_provenance_verified` = true) and (`o`.`averaged_across_plants` = false) and (not((`o`.`visual_review_status` like 'HOLD%'))) and (`pairs`.`link_status` = 'VERIFIED') and (`pairs`.`quality_status` = 'VERIFIED') and (`target`.`exists_on_export` = true) and (`pairs`.`image_exists` = true) and (`pairs`.`mask_exists` = true) and (`e`.`coordinate_unit` not in ('UNVERIFIED','UNKNOWN','')) and (`pairs`.`image_session_review_status` not in ('HOLD','CONFLICT','SUSPECTED_CONFLICT')) and (`pairs`.`image_session_crop` in ('lettuce','tomato')));
SET FOREIGN_KEY_CHECKS=1;
