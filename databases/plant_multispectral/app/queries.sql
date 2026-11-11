-- Run against the remote plant_multispectral database.
-- A row is one SAM single-plant capture, not one wavelength image.
SELECT * FROM v_batch_summary ORDER BY crop_code,batch_no;

SELECT batch_no,batch_name,light_code,captured_at,plant_number,
       ndvi_mean,ndvi_status,ndvi_value_basis,calibration_status,
       quality_status,L680,L800,mask_path
FROM v_singleplant_16_bands
ORDER BY batch_no,captured_at,light_order,plant_number
LIMIT 5;

-- 第2批 means batch_no=2; it is not a count of two batches.
SELECT * FROM v_singleplant_16_bands
WHERE batch_no=2 AND light_code='A-1'
ORDER BY captured_at,plant_number;

SELECT ndvi_status,quality_status,COUNT(*) AS observations
FROM v_singleplant_16_bands
GROUP BY ndvi_status,quality_status;

-- Generic long-form measurements support additional future indices.
SELECT o.id AS observation_id,d.code,d.algorithm_version,
       d.value_basis,d.calibration_status,m.calculation_status,m.index_mean
FROM plant_observations o
JOIN index_measurements m ON m.observation_id=o.id
JOIN index_definitions d ON d.id=m.definition_id
ORDER BY o.id,d.code;
