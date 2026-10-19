import ast

def load_functions(path, names, **extra_globals):
    """Parses a Python file with ast, extracts only named top-level functions/constants, and executes them in an isolated namespace."""
    with open(path, "r", encoding="utf-8") as f:
        source_code = f.read()
    
    tree = ast.parse(source_code, filename=str(path))
    body = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign)):
            if isinstance(node, ast.Assign):
                target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if any(n in names for n in target_names):
                    body.append(node)
            elif node.name in names:
                body.append(node)
                
    new_tree = ast.Module(body=body, type_ignores=[])
    code = compile(new_tree, filename=str(path), mode="exec")
    
    namespace = {"__file__": str(path)}
    namespace.update(extra_globals)
    exec(code, namespace)
    return namespace