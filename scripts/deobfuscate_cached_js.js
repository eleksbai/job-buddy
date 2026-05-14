const fs = require("fs");
const path = require("path");
const recast = require("recast");
const babelParser = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const t = require("@babel/types");

const files = process.argv.slice(2);
const moduleClassifications = {};

if (files.length === 0) {
  console.error("Usage: node scripts/deobfuscate_cached_js.js <file...>");
  process.exit(1);
}

const parser = {
  parse(source) {
    return babelParser.parse(source, {
      sourceType: "script",
      allowReturnOutsideFunction: true,
      plugins: [
        "jsx",
        "classProperties",
        "objectRestSpread",
        "optionalChaining",
        "nullishCoalescingOperator",
        "dynamicImport",
      ],
    });
  },
};

function isSafeIdentifierName(name) {
  return /^[$A-Z_a-z][$\w]*$/.test(name);
}

function renameFunctionParams(functionPath, names) {
  const params = functionPath.node.params;
  if (params.length !== names.length) {
    return;
  }

  for (let index = 0; index < names.length; index += 1) {
    const param = params[index];
    const targetName = names[index];
    if (!t.isIdentifier(param) || param.name === targetName) {
      continue;
    }
    functionPath.scope.rename(param.name, targetName);
  }
}

function renameWebpackModuleWrappers(ast) {
  traverse(ast, {
    CallExpression(path) {
      const { callee, arguments: args } = path.node;
      if (
        !t.isMemberExpression(callee) ||
        !t.isIdentifier(callee.property, { name: "push" }) ||
        args.length === 0 ||
        !t.isArrayExpression(args[0]) ||
        args[0].elements.length < 2
      ) {
        return;
      }

      const moduleMap = args[0].elements[1];
      if (!t.isObjectExpression(moduleMap)) {
        return;
      }

      for (const property of moduleMap.properties) {
        if (!t.isObjectProperty(property) || !t.isFunctionExpression(property.value)) {
          continue;
        }

        const wrapperPath = path.get("arguments.0.elements.1.properties").find(
          (propPath) => propPath.node === property
        );
        if (!wrapperPath) {
          continue;
        }

        const functionPath = wrapperPath.get("value");
        if (property.value.params.length === 3) {
          renameFunctionParams(functionPath, ["module", "exports", "require"]);
        } else if (property.value.params.length === 2) {
          renameFunctionParams(functionPath, ["module", "exports"]);
        }
      }
    },
  });
}

function buildUniqueName(scope, baseName) {
  let candidate = baseName;
  let counter = 2;
  while (
    scope.hasBinding(candidate) ||
    scope.hasGlobal(candidate) ||
    scope.hasReference(candidate)
  ) {
    candidate = `${baseName}${counter}`;
    counter += 1;
  }
  return candidate;
}

function renameTopLevelWrappers(ast) {
  traverse(ast, {
    Program(programPath) {
      const firstStatement = programPath.node.body[0];
      if (
        !t.isExpressionStatement(firstStatement) ||
        !t.isCallExpression(firstStatement.expression) ||
        !t.isFunctionExpression(firstStatement.expression.callee)
      ) {
        return;
      }

      const outerWrapperPath = programPath.get("body.0.expression.callee");
      if (outerWrapperPath.node.params.length === 2) {
        renameFunctionParams(outerWrapperPath, ["globalObject", "factory"]);
      }

      outerWrapperPath.traverse({
        ReturnStatement(returnPath) {
          if (!t.isFunctionExpression(returnPath.node.argument)) {
            return;
          }
          const returnedWrapperPath = returnPath.get("argument");
          if (returnedWrapperPath.node.params.length === 1) {
            renameFunctionParams(returnedWrapperPath, ["modules"]);
          }
        },
      });
    },
  });
}

function renameWebpackBootstrapInternals(ast) {
  traverse(ast, {
    Program(programPath) {
      const firstStatement = programPath.node.body[0];
      if (
        !t.isExpressionStatement(firstStatement) ||
        !t.isCallExpression(firstStatement.expression) ||
        !t.isFunctionExpression(firstStatement.expression.callee)
      ) {
        return;
      }

      const outerWrapperPath = programPath.get("body.0.expression.callee");
      outerWrapperPath.traverse({
        ReturnStatement(returnPath) {
          if (!t.isFunctionExpression(returnPath.node.argument)) {
            return;
          }

          const bootstrapPath = returnPath.get("argument");
          const bodyPaths = bootstrapPath.get("body.body");
          for (const statementPath of bodyPaths) {
            if (!statementPath.isVariableDeclaration()) {
              continue;
            }

            for (const declaratorPath of statementPath.get("declarations")) {
              const idPath = declaratorPath.get("id");
              const initPath = declaratorPath.get("init");
              if (!idPath.isIdentifier() || !initPath.node) {
                continue;
              }

              let semanticName = null;
              if (initPath.isObjectExpression()) {
                const properties = initPath.node.properties;
                if (properties.length === 0) {
                  semanticName = "installedModules";
                } else if (
                  properties.length === 1 &&
                  t.isObjectProperty(properties[0]) &&
                  t.isNumericLiteral(properties[0].key, { value: 0 }) &&
                  t.isNumericLiteral(properties[0].value, { value: 0 })
                ) {
                  semanticName = idPath.node.name === "r" ? "installedCssChunks" : "installedChunks";
                }
              } else if (initPath.isArrayExpression()) {
                semanticName = "deferredModules";
              }

              if (!semanticName || idPath.node.name === semanticName) {
                continue;
              }

              bootstrapPath.scope.rename(
                idPath.node.name,
                buildUniqueName(bootstrapPath.scope, semanticName)
              );
            }
          }
        },
      });
    },
  });
}

function renameSemanticModuleLocals(ast) {
  traverse(ast, {
    FunctionExpression(functionPath) {
      if (!functionPath.parentPath.isObjectProperty()) {
        return;
      }

      const moduleScope = functionPath.scope;
      const componentCandidates = new Map();

      functionPath.traverse({
        VariableDeclarator(path) {
          const { node } = path;
          if (!t.isIdentifier(node.id) || !node.init) {
            return;
          }

          if (
            t.isObjectExpression(node.init) &&
            node.init.properties.some(
              (property) =>
                t.isObjectProperty(property) &&
                t.isIdentifier(property.key, { name: "name" }) &&
                t.isStringLiteral(property.value)
            )
          ) {
            const nameProperty = node.init.properties.find(
              (property) =>
                t.isObjectProperty(property) &&
                t.isIdentifier(property.key, { name: "name" }) &&
                t.isStringLiteral(property.value)
            );
            const componentName = nameProperty.value.value.replace(/[^A-Za-z0-9_$]/g, "");
            const nextName = buildUniqueName(moduleScope, `${componentName}Options`);
            componentCandidates.set(node.id.name, { componentName, optionsName: nextName });
            moduleScope.rename(node.id.name, nextName);
            return;
          }

          if (
            t.isCallExpression(node.init) &&
            t.isMemberExpression(node.init.callee) &&
            t.isIdentifier(node.init.callee.property, { name: "a" }) &&
            node.init.arguments.length > 0 &&
            t.isIdentifier(node.init.arguments[0])
          ) {
            const sourceName = node.init.arguments[0].name;
            const componentCandidate = componentCandidates.get(sourceName);
            if (componentCandidate) {
              const normalizedName = buildUniqueName(
                moduleScope,
                `${componentCandidate.componentName}Component`
              );
              moduleScope.rename(node.id.name, normalizedName);
              return;
            }
          }

          if (t.isArrayExpression(node.init) && node.init.elements.every((element) => t.isObjectExpression(element) || t.isNullLiteral(element))) {
            if (/^[a-zA-Z_$][\w$]*$/.test(node.id.name) && node.init.elements.length > 0) {
              const firstElement = node.init.elements.find((element) => t.isObjectExpression(element));
              if (
                firstElement &&
                firstElement.properties.some(
                  (property) =>
                    t.isObjectProperty(property) &&
                    t.isIdentifier(property.key, { name: "path" })
                )
              ) {
                moduleScope.rename(
                  node.id.name,
                  buildUniqueName(moduleScope, "routeRecords")
                );
              }
            }
          }
        },
      });
    },
  });
}

function simplifyMinifiedNodes(ast) {
  traverse(ast, {
    UnaryExpression(path) {
      const { operator, argument } = path.node;
      if (operator !== "!" || !t.isNumericLiteral(argument)) {
        return;
      }
      if (argument.value === 0) {
        path.replaceWith(t.booleanLiteral(true));
      } else if (argument.value === 1) {
        path.replaceWith(t.booleanLiteral(false));
      }
    },
    MemberExpression(path) {
      const { computed, property } = path.node;
      if (!computed || !t.isStringLiteral(property) || !isSafeIdentifierName(property.value)) {
        return;
      }
      path.node.computed = false;
      path.node.property = t.identifier(property.value);
    },
    ExpressionStatement(path) {
      if (!t.isSequenceExpression(path.node.expression)) {
        return;
      }
      const expressions = path.node.expression.expressions.map((expression) =>
        t.expressionStatement(expression)
      );
      path.replaceWithMultiple(expressions);
    },
  });
}

function classifyModule(moduleFunctionPath) {
  const code = printAst(moduleFunctionPath.node);
  if (code.includes("router-view") || code.includes("router-link")) {
    return "router-runtime";
  }
  if (code.includes("path:") && code.includes("component:")) {
    return "route-config";
  }
  if (code.includes("name:") && code.includes("$createElement")) {
    return "vue-component";
  }
  if (code.includes("exports.default")) {
    return "es-module";
  }
  if (code.includes("module.exports=require.p+")) {
    return "asset-path";
  }
  if (code.includes("createQRCode") || code.includes("QRCode")) {
    return "qr-code";
  }
  if (code.includes("BossWxScan") || code.includes("SmsForm") || code.includes("login")) {
    return "login-flow";
  }
  if (code.includes("core-js") || code.includes("ArrayBuffer") || code.includes("Promise")) {
    return "polyfill";
  }
  if (code.includes("axios") || code.includes("XMLHttpRequest")) {
    return "http-client";
  }
  return "runtime-or-helper";
}

function collectModuleClassification(file, ast) {
  const modules = [];
  let collectedFromChunkPush = false;

  function pushModuleRecord(propertyPath) {
    const keyNode = propertyPath.node.key;
    const moduleId = t.isIdentifier(keyNode)
      ? keyNode.name
      : t.isStringLiteral(keyNode)
        ? keyNode.value
        : t.isNumericLiteral(keyNode)
          ? String(keyNode.value)
          : recast.print(keyNode).code;

    const functionPath = propertyPath.get("value");
    const printed = printAst(functionPath.node);
    const nameMatch = printed.match(/name:\s*"([^"]+)"/);
    modules.push({
      id: moduleId,
      category: classifyModule(functionPath),
      componentName: nameMatch ? nameMatch[1] : null,
    });
  }

  traverse(ast, {
    CallExpression(path) {
      const { callee, arguments: args } = path.node;
      if (
        !t.isMemberExpression(callee) ||
        !t.isIdentifier(callee.property, { name: "push" }) ||
        args.length === 0 ||
        !t.isArrayExpression(args[0]) ||
        args[0].elements.length < 2 ||
        !t.isObjectExpression(args[0].elements[1])
      ) {
        return;
      }

      for (const propertyPath of path.get("arguments.0.elements.1.properties")) {
        if (!propertyPath.isObjectProperty() || !propertyPath.get("value").isFunctionExpression()) {
          continue;
        }
        pushModuleRecord(propertyPath);
      }

      collectedFromChunkPush = true;
      path.stop();
    },
  });

  if (!collectedFromChunkPush) {
    traverse(ast, {
      FunctionExpression(path) {
        if (
          path.node.params.length === 1 &&
          t.isIdentifier(path.node.params[0], { name: "modules" })
        ) {
          path.traverse({
            CallExpression(callPath) {
              const firstArg = callPath.node.arguments[0];
              if (!t.isObjectExpression(firstArg)) {
                return;
              }

              const allModuleProperties = firstArg.properties.every(
                (property) =>
                  t.isObjectProperty(property) &&
                  propertyPathLikeModule(property)
              );
              if (!allModuleProperties) {
                return;
              }

              for (const propertyPath of callPath.get("arguments.0.properties")) {
                pushModuleRecord(propertyPath);
              }
              callPath.stop();
            },
          });
          path.stop();
        }
      },
    });
  }

  moduleClassifications[path.basename(file)] = modules;
}

function propertyPathLikeModule(property) {
  return (
    t.isFunctionExpression(property.value) &&
    (t.isStringLiteral(property.key) ||
      t.isIdentifier(property.key) ||
      t.isNumericLiteral(property.key))
  );
}

function printAst(ast) {
  return recast.print(ast, {
    quote: "double",
    trailingComma: false,
    tabWidth: 2,
    wrapColumn: 100,
    objectCurlySpacing: false,
    reuseWhitespace: false,
    arrayBracketSpacing: false,
  }).code;
}

for (const file of files) {
  const fullPath = path.resolve(file);
  const source = fs.readFileSync(fullPath, "utf8");
  const ast = recast.parse(source, { parser });

  renameWebpackModuleWrappers(ast);
  renameTopLevelWrappers(ast);
  renameWebpackBootstrapInternals(ast);
  renameSemanticModuleLocals(ast);
  simplifyMinifiedNodes(ast);
  collectModuleClassification(file, ast);

  const output = printAst(ast);
  fs.writeFileSync(fullPath, `${output.trimEnd()}\n`, "utf8");
  console.log(`Deobfuscated ${file}`);
}

const classificationPath = path.resolve("scripts/cache/js/module-classification.json");
fs.writeFileSync(classificationPath, `${JSON.stringify(moduleClassifications, null, 2)}\n`, "utf8");
console.log(`Wrote ${classificationPath}`);
