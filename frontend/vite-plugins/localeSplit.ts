import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import type { Plugin } from 'vite'

/**
 * Serves one catalogue per language (`virtual:oyuns-locale/<mn|ru|en>`) built from the
 * domain files in `src/locales`, so the app downloads only the language in use instead of
 * all three. Authoring is unchanged: each domain file stays one
 * `defineMessages({ mn, ru, en })` call, and `locales/index.ts` stays the registry of domains.
 *
 * The language object is lifted out of each domain file at build time, which only works for
 * plain string values; anything else fails the build with the file and key.
 */
const PREFIX = 'virtual:oyuns-locale/'
const RESOLVED = '\0' + PREFIX
const LANGUAGES = ['mn', 'ru', 'en']
const localesDir = fileURLToPath(new URL('../src/locales/', import.meta.url))

function parse(file: string) {
  return ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.ES2022, true)
}

/** Default-imported relative modules of `locales/index.ts`, i.e. the registered domains. */
function domainFiles(): string[] {
  const index = parse(localesDir + 'index.ts')
  const files: string[] = []
  for (const statement of index.statements) {
    if (!ts.isImportDeclaration(statement) || !statement.importClause?.name) continue
    const specifier = (statement.moduleSpecifier as ts.StringLiteral).text
    if (specifier.startsWith('./')) files.push(localesDir + specifier.slice(2) + '.ts')
  }
  return files
}

const propertyName = (name: ts.PropertyName) => (ts.isIdentifier(name) || ts.isStringLiteralLike(name) ? name.text : undefined)

function unwrap(node: ts.Expression): ts.Expression {
  while (ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isParenthesizedExpression(node)) node = node.expression
  return node
}

function languageSource(file: string, language: string): string {
  const source = parse(file)
  let found: string | undefined
  const visit = (node: ts.Node) => {
    if (found !== undefined) return
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === 'defineMessages') {
      const [set] = node.arguments
      const object = set && unwrap(set)
      if (!object || !ts.isObjectLiteralExpression(object)) throw new Error(`[locale-split] ${file}: defineMessages() needs an object literal`)
      for (const property of object.properties) {
        if (!ts.isPropertyAssignment(property) || propertyName(property.name) !== language) continue
        const messages = unwrap(property.initializer)
        if (!ts.isObjectLiteralExpression(messages)) throw new Error(`[locale-split] ${file}: "${language}" must be an object literal`)
        for (const entry of messages.properties) {
          if (!ts.isPropertyAssignment(entry) || !ts.isStringLiteralLike(unwrap(entry.initializer))) {
            throw new Error(`[locale-split] ${file}: "${language}" may only hold plain string values (see ${entry.getText(source).slice(0, 60)})`)
          }
        }
        found = messages.getText(source)
        return
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  if (found === undefined) throw new Error(`[locale-split] ${file}: no "${language}" messages found in defineMessages()`)
  return found
}

export function localeSplit(): Plugin {
  return {
    name: 'oyuns-locale-split',
    resolveId(id) {
      if (id.startsWith(PREFIX) && LANGUAGES.includes(id.slice(PREFIX.length))) return '\0' + id
    },
    load(id) {
      if (!id.startsWith(RESOLVED)) return
      const language = id.slice(RESOLVED.length)
      const files = domainFiles()
      this.addWatchFile(localesDir + 'index.ts')
      const parts = files.map((file) => {
        this.addWatchFile(file)
        return languageSource(file, language)
      })
      return `export default Object.assign({}, ${parts.join(',\n')})\n`
    },
    handleHotUpdate({ file, server }) {
      if (!file.startsWith(localesDir)) return
      for (const language of LANGUAGES) {
        const module = server.moduleGraph.getModuleById(RESOLVED + language)
        if (module) server.moduleGraph.invalidateModule(module)
      }
      server.ws.send({ type: 'full-reload' })
      return []
    },
  }
}
