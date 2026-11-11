-- One row per observed plant at one capture, with one selected CSV.
SELECT observation_key,captured_at,crop,physical_plant_id_candidate,
       linked_image_count,pGH_proxy,pMW_proxy,coordinate_unit,csv_path,visual_review_status
FROM p3d_v_observations
WHERE linked_image_count>0
ORDER BY captured_at LIMIT 5;

-- Multiple camera inputs sharing the SAME plant/date target, not independent samples.
SELECT observation_key,captured_at,camera_code,frame_index,image_host,image_path,csv_path,link_status
FROM p3d_v_image_csv_pairs
WHERE observation_key='rawobs-01b76bc7528e8159-c01'
ORDER BY camera_code,frame_index LIMIT 5;

-- Only formally admitted training pairs. Currently empty by design.
SELECT * FROM p3d_v_training_ready LIMIT 5;

-- Completed segmentation runs; no_detection is distinct from program error.
SELECT capture_set,run_status,total_images,processed_images,detected_instances,no_detection_images,error_count
FROM p3d_processing_runs;

-- Explicitly distinguish conversions, observed components, and verified samples.
SELECT 'csv_versions' AS item,COUNT(*) AS row_count FROM p3d_csv_exports
UNION ALL SELECT 'candidate_observations',COUNT(*) FROM p3d_observations
UNION ALL SELECT 'linked_image_views',COUNT(*) FROM p3d_observation_images
UNION ALL SELECT 'training_ready_pairs',COUNT(*) FROM p3d_v_training_ready;
