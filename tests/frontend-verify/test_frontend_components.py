#!/usr/bin/env python3
"""
TypeScript compilation and frontend component verification
"""
import subprocess
import os
import sys
import json

def run_command(cmd, cwd=None):
    """Run a shell command and return stdout, stderr, returncode"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
    return result.stdout, result.stderr, result.returncode

def test_typescript_compilation():
    """Test TypeScript compilation"""
    print("\n" + "=" * 60)
    print("Testing TypeScript Compilation")
    print("=" * 60)
    
    frontend_dir = "/home/l/rag-dashboard/src/frontend/web"
    
    # Check if tsconfig exists
    tsconfig_path = os.path.join(frontend_dir, "tsconfig.json")
    if not os.path.exists(tsconfig_path):
        print("❌ tsconfig.json not found")
        return False
    
    # Run TypeScript check
    stdout, stderr, rc = run_command("npx tsc --noEmit", cwd=frontend_dir)
    
    if rc == 0:
        print("✅ TypeScript compilation passed")
        return True
    else:
        # Show first few errors
        lines = stderr.split('\n')[:10]
        print("❌ TypeScript compilation failed:")
        for line in lines:
            if line.strip():
                print(f"   {line}")
        return False

def test_learning_page_component():
    """Check if LearningPage component exists and is valid"""
    print("\n" + "=" * 60)
    print("Testing LearningPage Component")
    print("=" * 60)
    
    learning_page_file = "/home/l/rag-dashboard/src/frontend/web/src/pages/LearningPage.tsx"
    
    if not os.path.exists(learning_page_file):
        print("❌ LearningPage.tsx not found")
        return False
    
    print("✅ LearningPage.tsx found")
    
    # Check for required Tab components
    with open(learning_page_file, 'r') as f:
        content = f.read()
    
    required_components = [
        "DashboardPanel",
        "ProblemsPanel", 
        "ReviewsPanel",
        "ImprovementHistoryPanel"
    ]
    
    missing = []
    for component in required_components:
        if component not in content:
            missing.append(component)
    
    if missing:
        print(f"❌ Missing components: {', '.join(missing)}")
        return False
    
    print("✅ All required components imported")
    
    # Check for tab definitions
    tabs = ['dashboard', 'problems', 'reviews', 'history', 'signals']
    missing_tabs = []
    for tab in tabs:
        if f"'{tab}'" not in content and f'"{tab}"' not in content:
            missing_tabs.append(tab)
    
    if missing_tabs:
        print(f"❌ Missing tab definitions: {', '.join(missing_tabs)}")
        return False
    
    print(f"✅ All {len(tabs)} tabs defined")
    return True

def test_learning_components():
    """Check learning component files"""
    print("\n" + "=" * 60)
    print("Testing Learning Components")
    print("=" * 60)
    
    components_dir = "/home/l/rag-dashboard/src/frontend/web/src/components/learning"
    
    if not os.path.isdir(components_dir):
        print(f"❌ Components directory not found: {components_dir}")
        return False
    
    print("✅ Components directory found")
    
    required_files = [
        "DashboardPanel.tsx",
        "ProblemsPanel.tsx",
        "ReviewsPanel.tsx",
        "ImprovementHistoryPanel.tsx",
        "DashboardPanel.css",
        "ProblemsPanel.css",
        "ReviewsPanel.css",
        "ImprovementHistoryPanel.css"
    ]
    
    missing = []
    for file in required_files:
        file_path = os.path.join(components_dir, file)
        if not os.path.exists(file_path):
            missing.append(file)
    
    if missing:
        print(f"❌ Missing files: {', '.join(missing)}")
        return False
    
    print(f"✅ All {len(required_files)} component files present")
    return True

def test_css_files():
    """Test CSS files for required styles"""
    print("\n" + "=" * 60)
    print("Testing CSS Styles")
    print("=" * 60)
    
    css_files = [
        "/home/l/rag-dashboard/src/frontend/web/src/pages/LearningPage.css",
        "/home/l/rag-dashboard/src/frontend/web/src/components/learning/DashboardPanel.css",
    ]
    
    all_valid = True
    for css_file in css_files:
        if not os.path.exists(css_file):
            print(f"❌ CSS file not found: {css_file}")
            all_valid = False
            continue
        
        with open(css_file, 'r') as f:
            content = f.read()
        
        if len(content) < 100:
            print(f"❌ CSS file too small: {css_file}")
            all_valid = False
        else:
            print(f"✅ CSS file valid: {os.path.basename(css_file)}")
    
    return all_valid

def main():
    print("=" * 60)
    print("Frontend Dashboard Verification Suite")
    print("=" * 60)
    
    results = {
        'typescript': test_typescript_compilation(),
        'learning_page': test_learning_page_component(),
        'components': test_learning_components(),
        'css': test_css_files(),
    }
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"Summary: {passed}/{total} tests passed")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    return passed == total

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
