# Glossary

Short definitions for words used in this project. Skip anything you do not need yet.

**App URL**  
The website being tested. Set it in the control panel or in `config.json` (`appUrl`). The GDC Portal value that ships with this folder is only an example.

**Assertion**  
A line of code that decides pass or fail (for example, “this heading is visible”). Recording clicks does not write this line.

**Backlog**  
The Excel list of test cases (`backlog/playwright-test-backlog.xlsx`). Source of truth for *what* to check, not the history of each run.

**Codegen**  
Playwright’s recorder: you click the real site; it writes the matching clicks into a test file.

**Command / terminal**  
The text window where you type instructions such as `npm start`.

**Control panel**  
The local web page started by `npm start` (`app/streamlit_app.py`). Buttons there run the tools for you.

**Git**  
A history of file changes. A **commit** is one snapshot with a message. A **repository** is a project folder git is tracking.

**npm**  
The installer for JavaScript libraries. `npm install` reads `package.json` and fills `node_modules/`.

**pip**  
The installer for Python libraries. `pip install -r requirements.txt` is the Python equivalent of `npm install`.

**Playwright**  
The tool that opens a browser, performs the recorded steps, and reports pass/fail.

**Skeleton**  
A starter test file generated from an Excel row. It has placeholders until you record clicks (and later write an assertion).

**Spec**  
A test file, here `tests/*.spec.js`. “Spec” is short for specification.

**Streamlit**  
The Python library that draws the control panel in your browser.

**Test ID**  
The unique name of a case (`GDC-001`, `UI-005`). It appears in Excel, in the spec title, and in the results log.

**Trace**  
A recording of one test run (clicks, screenshots) you can replay with `npx playwright show-trace`.
