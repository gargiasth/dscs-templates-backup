# Test Generation Prompt
Some tests have been auto-generated with the use of LLMs with the following prompts. In order to use the prompt, the LLM must have a requirements  list and access to the file where the respective function resides.

## Prompt:

Write Unit Tests for the following function: spcs/schema_setup.py::create_schema

Write the test against the requirements, not implementation.

Requirements:
- If the schema does not exist → create it and log "Schema {database}.{schema} created successfully"
- If the schema already exists → skip creation and log "Schema {database}.{schema} already exists — skipping creation"
- If any error occurs → log the error and re-raise the exception
Libraries: You may use pytest, unittest, pytest-mock, unittest.mock, responses, httpretty, pytest-postgreql, sqlalchemy

Instructions:
1.	File Setup: save the test file under the tests/ folder. Name the file using the following pattern: test_<function_name>.py Example: tests/test_fetch_cases.py
2.	Naming Convention: name each test function using the following pattern: test_<function_name>_<path>_<what_it_tests>
3.	Use the AAA Pattern (Arrange–Act–Assert) to produce a structured and easy to maintain test.
4.	Include at least one Equivalence Class tests for each of the following partitions. Some paths may have multiple tests:
- Happy Path  - Verify that the function works correctly under ideal conditions and healthy environment. Test the most common use case
- Angry Path - Verify that the test fails gracefully by raising errors in non-ideal conditions.
- Delinquent path - Verify that the function handles malicious, unauthorized or unexpected inputs.
- Desolate path - Verify that the function handles empty, null or missing data. Test None/null values for every function that accepts optional parameters. Also verify that it returns an empty result or raises a clear exception. Don't assume empty = error; sometimes empty is valid based on use case.
- Forgetful path - Verify your function handles resource constraints, interruptions and timeouts.
5.	Include Black Box Test and verify observable behavior only. Verify inputs and outputs without knowledge of internal implementation. These tests should survive refactoring.
6.	Include both White Box tests and verify  internal implementation details, specific branches, conditions and internal logic you know the function uses.
7.	Logging assertions: where the function uses a logger, verify that the correct log level is called on success (logger.info) and on failure (logger.error).
8.	Test Independence: each test must be fully independent. No test should depend on the output or state of another test.
9.	No hardcoded external values: do not hardcode real API URLs, database credentials or file paths. Use mocks or fixtures instead. Use pytest.fixture for any shared test data or setup that is reused across multiple tests rather than repeating setup code.
10.	One assertion focus per test:  each test should verify one specific behavior. Avoid multiple unrelated assertions in a single test.
