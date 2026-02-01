import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd

class AppleHealthParser:
    def __init__(self, export_xml_path: str = None):
        self.export_xml_path = export_xml_path

    def parse_records(self, record_type: str, limit: int = 100):
        # 'HKQuantityTypeIdentifierStepCount', etc.
        if not self.export_xml_path:
            return []
            
        data = []
        try:
            # Iterative parsing to avoid loading massive XML into memory?
            # For MVP, assume it fits or user provides a filtered one.
            # actually export.xml can be huge (GBs). Iterparse is safer.
            
            context = ET.iterparse(self.export_xml_path, events=("end",))
            count = 0
            for event, elem in context:
                if elem.tag == "Record" and elem.attrib.get('type') == record_type:
                    data.append(elem.attrib)
                    count += 1
                    if limit and count >= limit:
                        break
                elem.clear()
            return data
        except Exception as e:
            print(f"Error parsing Apple Health XML: {e}")
            return []

    def get_steps(self, limit: int = 100):
        return self.parse_records("HKQuantityTypeIdentifierStepCount", limit)
        
    def get_workouts(self, limit: int = 50):
        # Workouts are slightly different tag usually "Workout"
        # reusing logic for now but might need specific Workout parser
        data = []
        if not self.export_xml_path:
            return []
            
        try:
            context = ET.iterparse(self.export_xml_path, events=("end",))
            count = 0
            for event, elem in context:
                if elem.tag == "Workout":
                    data.append(elem.attrib)
                    count += 1
                    if limit and count >= limit:
                        break
                elem.clear()
            return data
        except Exception as e:
             print(f"Error parsing Apple Health Workouts: {e}")
             return []
