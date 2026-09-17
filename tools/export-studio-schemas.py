"""Write portable JSON Schemas from the actual persisted record classes."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import records

names=('CaptureSession','Frame','CalibrationProfile','SurfacePatch','Atlas','MaterialAsset',
       'PrinterProfile','MeshValidationReport','PrintProject','ExportManifest','Specimen','ImpressionVariant')
schema={'schema_version':'material-studio/1','records':{name:getattr(records,name).model_json_schema() for name in names}}
destination=Path(__file__).resolve().parents[1]/'docs/records.schema.json'
destination.write_text(json.dumps(schema,indent=2),encoding='utf-8')
print(f'Exported {len(names)} record schemas.')
