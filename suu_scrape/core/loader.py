import importlib.util
import sys
import os
import glob
from typing import List, Type
from .base import PluginBase

def load_plugin_from_file(file_path: str) -> Type[PluginBase]:
    """
    Load a PluginBase subclass from a Python file.
    Expects the file to contain a class that inherits from PluginBase.
    """
    try:
        module_name = os.path.basename(file_path).replace('.py', '')
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        
        # Find the subclass of PluginBase
        for attribute_name in dir(module):
            attribute = getattr(module, attribute_name)
            if isinstance(attribute, type) and issubclass(attribute, PluginBase) and attribute is not PluginBase:
                return attribute
                
        raise ValueError(f"No PluginBase subclass found in {file_path}")
        
    except Exception as e:
        print(f"Failed to load plugin from {file_path}: {e}")
        return None

def discover_plugins(plugins_dir: str) -> List[Type[PluginBase]]:
    """
    Discover and load all plugins in the specified directory.
    """
    plugins = []
    search_path = os.path.join(plugins_dir, "*.py")
    for file_path in glob.glob(search_path):
        if "__init__" in file_path:
            continue
            
        plugin_class = load_plugin_from_file(file_path)
        if plugin_class:
            plugins.append(plugin_class)
            
    return plugins
