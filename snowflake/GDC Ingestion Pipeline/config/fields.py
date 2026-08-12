# fields.py
## GDC field mappings and result limits for TCGA-BRCA
### Each mapping is a tuple of (gdc_api_path, flat_column_name, sqlalchemy_type)
### To add a field: add a tuple to the relevant mappings list
### To remove a field: delete the tuple — nothing else needs to change
### pk and fk are defined per entity and used to generate schemas automatically

from sqlalchemy import String, Float

# Project config
PROJECT_ID   = "TCGA-BRCA"
RESULT_LIMIT = 20000

# Case fields
CASE_PK = "case_id"
CASE_FK = []
CASE_FIELD_MAPPINGS = [
    ("case_id",              "case_id",      String),
    ("submitter_id",         "submitter_id", String),
    ("disease_type",         "disease_type", String),
    ("project.project_id",   "project_id",   String),
    ("diagnoses.morphology", "morphology",   String),
]

# Sample fields
SAMPLE_PK = "sample_id"
SAMPLE_FK = ["case_id"]
SAMPLE_FIELD_MAPPINGS = [
    ("case_id",                            "case_id",                    String),  # fk
    ("samples.sample_id",                  "sample_id",                  String),
    ("samples.sample_id",                  "sample_id",                  String),
    ("samples.submitter_id",               "submitter_id",               String),
    ("samples.sample_type",                "sample_type",                String),
    ("samples.specimen_type",              "specimen_type",              String),
    ("samples.tissue_type",                "tissue_type",                String),
    ("samples.tumor_descriptor",           "tumor_descriptor",           String),
    ("samples.preservation_method",        "preservation_method",        String),
    ("samples.initial_weight",             "initial_weight",             Float),
    ("samples.days_to_collection",         "days_to_collection",         Float),
    ("samples.days_to_sample_procurement", "days_to_sample_procurement", Float),
    ("samples.pathology_report_uuid",      "pathology_report_uuid",      String),
    ("samples.state",                      "state",                      String),
]

# Slide fields
SLIDE_PK = "slide_id"
SLIDE_FK = ["case_id", "sample_id"]
SLIDE_FIELD_MAPPINGS = [
    ("case_id",                                         "case_id",    String),  # fk
    ("samples.sample_id",                               "sample_id",  String),  # fk
    ("samples.portions.slides.slide_id",                "slide_id",   String),
    ("samples.portions.slides.slide_id",                        "slide_id",                        String),
    ("samples.portions.slides.submitter_id",                    "submitter_id",                    String),
    ("samples.portions.slides.section_location",                "section_location",                String),
    ("samples.portions.slides.state",                           "state",                           String),
    ("samples.portions.slides.percent_tumor_cells",             "percent_tumor_cells",             Float),
    ("samples.portions.slides.percent_tumor_nuclei",            "percent_tumor_nuclei",            Float),
    ("samples.portions.slides.percent_necrosis",                "percent_necrosis",                Float),
    ("samples.portions.slides.percent_stromal_cells",           "percent_stromal_cells",           Float),
    ("samples.portions.slides.percent_normal_cells",            "percent_normal_cells",            Float),
    ("samples.portions.slides.percent_neutrophil_infiltration", "percent_neutrophil_infiltration", Float),
    ("samples.portions.slides.percent_lymphocyte_infiltration", "percent_lymphocyte_infiltration", Float),
    ("samples.portions.slides.percent_monocyte_infiltration",   "percent_monocyte_infiltration",   Float),
]



# Silver case fields
SILVER_CASE_FIELD_MAPPINGS = [
    ("case_id",              "case_id",      String),
    ("submitter_id",         "submitter_id", String),
    ("disease_type",         "disease_type", String),
    ("project.project_id",   "project_id",   String),
    ("diagnoses.morphology", "morphology",   String),
]

# Silver sample fields
SILVER_SAMPLE_FIELD_MAPPINGS = [
    ("case_id",                                "case_id",                    String),
    ("samples.sample_id",                      "sample_id",                  String),
    ("samples.submitter_id",                   "submitter_id",               String),
    ("samples.sample_type",                    "sample_type",                String),
    ("samples.specimen_type",                  "specimen_type",              String),
    ("samples.tissue_type",                    "tissue_type",                String),
    ("samples.tumor_descriptor",               "tumor_descriptor",           String),
    ("samples.preservation_method",            "preservation_method",        String),
    ("samples.initial_weight",                 "initial_weight",             Float),
    ("samples.days_to_collection",             "days_to_collection",         Float),
    ("samples.days_to_sample_procurement",     "days_to_sample_procurement", Float),
    ("samples.pathology_report_uuid",          "pathology_report_uuid",      String),
    ("samples.state",                          "state",                      String),
]


# Gold fields
GOLD_PK = "sample_id"
GOLD_FK = []
GOLD_FIELD_MAPPINGS = [
    ("case_id",                                "case_id",                    String),
    ("submitter_id",                           "submitter_id",               String),
    ("disease_type",                           "disease_type",               String),
    ("project.project_id",                     "project_id",                 String),
    ("diagnoses.morphology",                   "morphology",                 String),
    ("samples.sample_id",                      "sample_id",                  String),
    ("samples.sample_type",                    "sample_type",                String),
    ("samples.specimen_type",                  "specimen_type",              String),
    ("samples.tissue_type",                    "tissue_type",                String),
    ("samples.tumor_descriptor",               "tumor_descriptor",           String),
    ("samples.preservation_method",            "preservation_method",        String),
    ("samples.initial_weight",                 "initial_weight",             Float),
    ("samples.days_to_collection",             "days_to_collection",         Float),
    ("samples.days_to_sample_procurement",     "days_to_sample_procurement", Float),
    ("samples.pathology_report_uuid",          "pathology_report_uuid",      String),
    ("samples.state",                          "state",                      String),
]


# API request fields — built automatically from all three mapping lists
CASE_FIELDS = (
    [api_path for api_path, _, _ in CASE_FIELD_MAPPINGS] +
    [api_path for api_path, _, _ in SAMPLE_FIELD_MAPPINGS] +
    [api_path for api_path, _, _ in SLIDE_FIELD_MAPPINGS]
)