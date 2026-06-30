#include <check.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* We need access to term.cwd and the osc7 handler. Include necessary headers. */
#include "../src/compositors/dwm/st/patch/osc7.c"

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

START_TEST(test_osc7_cwd_no_overflow)
{
    /* Invariant: term.cwd must never be written beyond its allocated size,
       regardless of how long the path in an OSC 7 sequence is. */

    /* Generate an overlong path that exceeds typical buffer sizes */
    char overflow_payload[8192];
    snprintf(overflow_payload, sizeof(overflow_payload), "file://localhost/");
    memset(overflow_payload + strlen(overflow_payload), 'A', 6000);
    overflow_payload[6000 + strlen("file://localhost/")] = '\0';

    /* Boundary: exactly PATH_MAX length path */
    char boundary_payload[PATH_MAX + 64];
    snprintf(boundary_payload, sizeof(boundary_payload), "file://localhost/");
    size_t prefix_len = strlen(boundary_payload);
    memset(boundary_payload + prefix_len, 'B', PATH_MAX - 1);
    boundary_payload[prefix_len + PATH_MAX - 1] = '\0';

    /* Valid short input */
    const char *valid_payload = "file://localhost/home/user";

    const char *payloads[] = {
        overflow_payload,
        boundary_payload,
        valid_payload,
    };
    int num_payloads = sizeof(payloads) / sizeof(payloads[0]);

    for (int i = 0; i < num_payloads; i++) {
        /* Clear cwd and surrounding memory sentinel */
        memset(term.cwd, 0, sizeof(term.cwd));

        /* Call the OSC 7 handler with the payload */
        osc7(payloads[i]);

        /* Security invariant: the string in term.cwd must fit within its bounds */
        size_t cwd_len = strnlen(term.cwd, sizeof(term.cwd));
        ck_assert_msg(cwd_len < sizeof(term.cwd),
            "term.cwd overflow detected with payload index %d (len=%zu, max=%zu)",
            i, cwd_len, sizeof(term.cwd));
    }
}
END_TEST

Suite *security_suite(void)
{
    Suite *s;
    TCase *tc_core;

    s = suite_create("Security");
    tc_core = tcase_create("Core");

    tcase_add_test(tc_core, test_osc7_cwd_no_overflow);
    suite_add_tcase(s, tc_core);

    return s;
}

int main(void)
{
    int number_failed;
    Suite *s;
    SRunner *sr;

    s = security_suite();
    sr = srunner_create(s);

    srunner_run_all(sr, CK_NORMAL);
    number_failed = srunner_ntests_failed(sr);
    srunner_free(sr);

    return (number_failed == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
}