#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef SMPLOS_ACTION_HELPER
#define SMPLOS_ACTION_HELPER "/usr/lib/smplos/signal-notification-activate"
#endif
#ifndef SMPLOS_ACTION_TIMEOUT_US
#define SMPLOS_ACTION_TIMEOUT_US 2000000
#endif

static bool smplos_signal_notification(const char *app, const char *desktop)
{
        return (app && g_ascii_strcasecmp(app, "Signal") == 0) ||
               (desktop && (g_ascii_strcasecmp(desktop, "signal") == 0 ||
                            g_ascii_strcasecmp(desktop, "signal-desktop") == 0 ||
                            g_ascii_strcasecmp(desktop, "org.signal.Signal") == 0));
}

static void smplos_signal_pre_forward(const char *recipient, const char *action,
                                     const char *app, const char *desktop)
{
        if (!recipient || !action || strcmp(action, "default") != 0 ||
            !smplos_signal_notification(app, desktop))
                return;

        struct sigaction disposition;
        if (sigaction(SIGCHLD, NULL, &disposition) != 0 ||
            disposition.sa_handler != SIG_DFL || (disposition.sa_flags & SA_NOCLDWAIT)) {
                LOG_W("Signal workspace preparation wait policy unavailable; forwarding native action");
                return;
        }
        const gint64 deadline = g_get_monotonic_time() + SMPLOS_ACTION_TIMEOUT_US;
        pid_t child = fork();
        if (child == 0) {
                if (setpgid(0, 0) != 0)
                        _exit(125);
                int nullfd = open("/dev/null", O_RDWR);
                if (nullfd < 0)
                        _exit(125);
                if (dup2(nullfd, STDIN_FILENO) < 0 ||
                    dup2(nullfd, STDOUT_FILENO) < 0 ||
                    dup2(nullfd, STDERR_FILENO) < 0)
                        _exit(125);
                if (nullfd > STDERR_FILENO)
                        close(nullfd);
                execl(SMPLOS_ACTION_HELPER, SMPLOS_ACTION_HELPER, recipient, (char *)NULL);
                _exit(127);
        }
        if (child < 0) {
                LOG_W("Signal workspace preparation unavailable; forwarding native action");
                return;
        }
        /* The child also sets this before exec; establish the kill boundary early. */
        (void)setpgid(child, child);
        int status = 0;
        while (g_get_monotonic_time() < deadline) {
                siginfo_t info = {0};
                int result = waitid(P_PID, child, &info, WEXITED | WNOHANG | WNOWAIT);
                if (result < 0 && errno == ECHILD) {
                        LOG_W("Signal workspace preparation wait failed; forwarding native action");
                        return;
                }
                if (result < 0 && errno != EINTR)
                        break;
                if (result == 0 && info.si_pid == child) {
                        if (info.si_code == CLD_EXITED && info.si_status == 0) {
                                while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
                                return;
                        }
                        break;
                }
                g_usleep(5000);
        }
        /* WNOWAIT retains the child identity until all owned-group kills finish. */
        (void)kill(-child, SIGKILL);
        (void)kill(child, SIGKILL);
        while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
        LOG_W("Signal workspace preparation failed; forwarding native action");
}
