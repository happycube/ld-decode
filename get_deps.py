#!/usr/bin/env python3
"""
Resolve all dependencies for specified packages and get download URLs and SHA256 hashes
from PyPI/files.pythonhosted.org
"""

import json
import sys
from urllib.request import urlopen
from urllib.error import URLError
from packaging.specifiers import SpecifierSet
from packaging.requirements import Requirement

# Packages to resolve with their versions
PACKAGES = {
    'numpy': '1.26.4',
    'scipy': '1.11.4',
    'matplotlib': '3.8.2',
    'numba': '0.58.1'
}

def get_pypi_info(package_name, version):
    """Get package info from PyPI JSON API"""
    url = f"https://pypi.org/pypi/{package_name}/{version}/json"
    try:
        with urlopen(url) as response:
            return json.loads(response.read().decode('utf-8'))
    except URLError as e:
        print(f"Error fetching {package_name}=={version}: {e}", file=sys.stderr)
        return None

def get_package_downloads(package_data):
    """Extract download URLs and hashes from package data"""
    if not package_data or 'releases' not in package_data:
        return {}
    
    results = {}
    version = package_data['info']['version']
    releases = package_data.get('releases', {})
    
    if version not in releases:
        return {}
    
    for file_info in releases[version]:
        filename = file_info.get('filename', '')
        # Prefer .tar.gz, fall back to .whl
        if filename.endswith(('.tar.gz', '.whl')):
            url = file_info.get('url', '')
            hashes = file_info.get('hashes', {})
            sha256 = hashes.get('sha256', '')
            
            if url and sha256:
                results[filename] = {
                    'url': url,
                    'sha256': sha256,
                    'python_version': file_info.get('python_version', 'source')
                }
    
    return results

def get_dependencies(package_name, version):
    """Get direct dependencies for a package"""
    info = get_pypi_info(package_name, version)
    if not info:
        return []
    
    requires = info.get('info', {}).get('requires_dist', [])
    if not requires:
        return []
    
    deps = []
    for req_str in requires:
        # Parse requirement string
        if not req_str:
            continue
        
        # Handle extras and environment markers
        if ';' in req_str:
            req_str = req_str.split(';')[0].strip()
        
        if 'extra ==' in req_str:
            continue
        
        try:
            req = Requirement(req_str)
            deps.append({
                'name': req.name,
                'specifier': str(req.specifier) if req.specifier else ''
            })
        except Exception as e:
            print(f"Warning: Could not parse requirement '{req_str}': {e}", file=sys.stderr)
    
    return deps

def resolve_version(package_name, specifier_str):
    """Resolve a specific version that matches the specifier"""
    try:
        info = get_pypi_info(package_name, 'latest')
        if info:
            version = info['info']['version']
            if specifier_str:
                spec = SpecifierSet(specifier_str)
                # For now, just use the version from specifier
                # In production, might need to find best match
                if spec.contains(version):
                    return version
            return version
    except:
        pass
    
    # Fallback: try to parse specifier to get version
    if specifier_str and '==' in specifier_str:
        return specifier_str.replace('==', '')
    
    return None

def resolve_all_dependencies(packages_dict):
    """Recursively resolve all dependencies"""
    processed = {}
    to_process = list(packages_dict.items())
    
    while to_process:
        package_name, version = to_process.pop(0)
        
        # Skip if already processed
        if (package_name, version) in processed:
            continue
        
        print(f"Processing {package_name}=={version}...", file=sys.stderr)
        
        # Get package info and dependencies
        deps = get_dependencies(package_name, version)
        
        for dep in deps:
            dep_name = dep['name'].lower()
            dep_specifier = dep['specifier']
            
            # Try to resolve the version
            dep_version = resolve_version(dep_name, dep_specifier)
            
            if dep_version and (dep_name, dep_version) not in processed:
                to_process.append((dep_name, dep_version))
        
        processed[(package_name, version)] = deps
    
    return processed

def main():
    """Main entry point"""
    print("Resolving all dependencies...", file=sys.stderr)
    
    # Resolve all dependencies
    all_packages = resolve_all_dependencies(PACKAGES)
    
    print("\nGathering download URLs and hashes...", file=sys.stderr)
    
    results = []
    
    # Add all resolved packages
    for (package_name, version), _ in sorted(all_packages.items()):
        print(f"Fetching {package_name}=={version}...", file=sys.stderr)
        
        info = get_pypi_info(package_name, version)
        if not info:
            print(f"Warning: Could not fetch info for {package_name}=={version}", file=sys.stderr)
            continue
        
        downloads = get_package_downloads(info)
        
        # Find the best file (prefer .tar.gz for source distributions)
        best_file = None
        best_url = None
        best_sha256 = None
        
        for filename, file_data in downloads.items():
            if filename.endswith('.tar.gz') or filename.endswith('.whl'):
                best_file = filename
                best_url = file_data['url']
                best_sha256 = file_data['sha256']
                if filename.endswith('.tar.gz'):
                    break
        
        if best_url and best_sha256:
            results.append(f"{package_name}=={version}|{best_url}|{best_sha256}")
        else:
            print(f"Warning: No suitable download found for {package_name}=={version}", file=sys.stderr)
    
    print("\n" + "="*80, file=sys.stderr)
    print("Package Download URLs and Hashes:", file=sys.stderr)
    print("="*80 + "\n", file=sys.stderr)
    
    for result in results:
        print(result)

if __name__ == '__main__':
    main()
