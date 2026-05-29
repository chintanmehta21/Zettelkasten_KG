## PEP 701: Overview and Motivation
- Accepted for Python 3.12, formalizes f-string syntax.
- Provides a PEG grammar and integrates f-strings directly into the parser.
- Lifts restrictions from PEP 498.
- Authored by Pablo Galindo Salgado, Batuhan Taskaya, Lysandros Nikolaou, and Marta Gómez Macías.
- Aims to reduce CPython parser maintenance cost and improve user experience.
- Previous implementation treated f-strings as `STRING` tokens, requiring error-prone post-processing.
- Prevented the use of the new PEG parser's (PEP 617) improved error messages.
- Lacked a formal grammar for other Python implementations (e.g., PyPy) to follow.

## Key Changes and Lifted Limitations
- Lifts several limitations originally imposed due to CPython's old lexer.
- The new grammar defines the expression component as 'any applicable Python expression'.
- Allows for arbitrary nesting of f-strings, with a mandated minimum nesting depth of 5.
- Specifies a minimum nesting depth of 2 for expressions within format specifiers (e.g., `f"{'':*^{1:{1}}}"` must be valid).
- Changes are designed to be backwards-compatible, preserving the existing Abstract Syntax Tree (AST).
- Introduces no semantic changes to existing code.
- The f-string debug feature (`f"{expr=}"`), introduced in Python 3.8, is unaffected, but its formal handling requires the lexer to preserve the raw string of the expression, including whitespace.

### Quote Reuse
- The same quote character delimiting the f-string can now be used within an expression part (e.g., `f"key: {my_dict['key']}"`).
- Acknowledged as controversial by some due to readability concerns and challenges for simple syntax highlighters (like IDLE's).
- Arguments in favor include consistency with other languages (JavaScript, Ruby, C#), simplification for code generators (`ast.unparse`), and significantly reduced implementation complexity in the PEG parser.
- Authors decided against forbidding quote reuse at the parser level, suggesting it be handled by linters.

### Backslashes
- Backslashes and escape sequences are now allowed inside expression parts (e.g., `f"{'
'.join(items)}"`).

### Comments
- The `#` character for comments is now permitted within multi-line f-string expressions.
- Requires the closing brace `}` to be on a subsequent line.

### Newlines
- Newlines are allowed within expression brackets.

## Implementation Details
- To support the new grammar, three new tokens are introduced: `FSTRING_START`, `FSTRING_MIDDLE`, and `FSTRING_END`.
- The `tokenize` module will be updated to emit these new tokens.
- The PEP provides a reference algorithm for adapting lexers using a stack of modes.

## Rejected Ideas and Simplified Teaching
- Two ideas were rejected:
- 1. Lifting the restriction that expressions with top-level `:` or `!` characters (like lambdas) must be parenthesized.
- 2. Allowing escaped braces (`\{`, `\}`).
- Allowing escaped braces (`\{`, `\}`) was deferred as a potential future enhancement.
- The new, simpler way to teach f-strings is: 'You can place any valid Python expression inside an f-string expression, and everything after a `:` character at the top level will be identified as a format specification.'
- A reference implementation is available.