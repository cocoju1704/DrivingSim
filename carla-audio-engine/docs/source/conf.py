import os
import sys
from unittest.mock import MagicMock

# 1. Path Setup: We add both the Root and the Subfolders
current_dir = os.path.dirname(__file__)
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
src_path = os.path.join(project_root, "src")

sys.path.insert(0, project_root) # Supports 'from src.xxx'
sys.path.insert(0, src_path)     # Supports 'from CARLA.xxx'
sys.path.insert(0, os.path.join(src_path, "CARLA")) # Supports 'from Classes.xxx'
sys.path.insert(0, os.path.join(src_path, "FMOD"))  # Supports 'from Adapters.xxx'

# 1. Define all modules and submodules that need to be "faked"
MOCK_MODULES = [
    'carla', 
    'numpy', 
    'pygame', 
    'pygame.locals', 
    'pyfmodex', 
    'pyfmodex.studio', 
    'pyfmodex.studio.enums', 
    'pyfmodex.exceptions', 
    'pyfmodex.enums', 
    'pyfmodex.flags', 
    'pyfmodex.structures'
]

# 2. Inject them into sys.modules as standard MagicMocks
for mod_name in MOCK_MODULES:
    sys.modules[mod_name] = MagicMock()

# -- Project information -----------------------------------------------------
project = 'SoundCARLA'
copyright = '2026, Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong'
author = 'Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong'
release = '0.1'

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',      # Liest deine Docstrings
    'sphinx.ext.intersphinx',
    'sphinx.ext.napoleon',     # Versteht den Google-Style
    'sphinx.ext.viewcode',     # Fügt Links zum Quellcode hinzu
    'sphinx_rtd_theme',        # Das schicke Read-the-Docs Design
    'sphinx.ext.extlinks'
]

intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'numpy': ('https://numpy.org/doc/stable/', None),
    'pygame': ('https://www.pygame.org/docs/', None),
}

extlinks = {
    'carla_docs': ('https://carla.readthedocs.io/en/0.9.15/%s', '%s')
}

# Napoleon settings
napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_use_param = True
napoleon_use_rtype = True
autodoc_member_order = 'bysource'

templates_path = ['_templates']
exclude_patterns = []

# -- Options for HTML output -------------------------------------------------
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
add_module_names = False

html_theme_options = {
    'collapse_navigation': False,
    'sticky_navigation': True,
    'navigation_depth': 4,
    'includehidden': True,
    'titles_only': False
}

# -- Custom Setup Hook -------------------------------------------------------
def setup(app):
    def skip(app, what, name, obj, skip, options):
        # Adjusted names to match what Sphinx is actually seeing in your logs
        clean_modules = [
            "src.CARLA.generate_traffic",
            "src.CARLA.manual_control_sw",
            "CARLA.generate_traffic",
            "CARLA.manual_control_sw"
        ]
        
        module_name = getattr(obj, "__module__", None)

        if module_name in clean_modules:
            return True 
            
        return skip

    app.connect("autodoc-skip-member", skip)

 # -- Override dynamic paths for documentation --------------------------------

try:
    import sys
    import src.FMOD.Banks.config as fmod_config
    from src.FMOD.Banks.EnvironmentBank import EnvironmentBank
    from src.FMOD.Banks.TriggerBank import TriggerBank
    
    fmod_config.TRIGGER_BANK_PATH = 'path/to/trigger_bank'
    fmod_config.ENVIRONMENT_BANK_PATH = 'path/to/environment_bank'
    EnvironmentBank.DEFAULT_BANK_PATH = 'path/to/environment_bank'
    TriggerBank.DEFAULT_BANK_PATH = 'path/to/trigger_bank'
    
    if 'src.FMOD.Banks.config' in sys.modules:
        sys.modules['src.FMOD.Banks.config'].TRIGGER_BANK_PATH = 'path/to/trigger_bank'
        sys.modules['src.FMOD.Banks.config'].ENVIRONMENT_BANK_PATH = 'path/to/environment_bank'

    if 'src.FMOD.Banks.EnvironmentBank' in sys.modules:
        sys.modules['src.FMOD.Banks.EnvironmentBank'].EnvironmentBank.DEFAULT_BANK_PATH = 'path/to/environment_bank'
        sys.modules['src.FMOD.Banks.TriggerBank'].TriggerBank.DEFAULT_BANK_PATH = 'path/to/trigger_bank'
    
except Exception as e:
    pass