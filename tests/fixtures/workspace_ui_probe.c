/* Test-only GTK module: inspect real EWW allocations in isolated Xvfb. */
#include <gtk/gtk.h>
#include <stdio.h>

static const char *request_path;
static const char *response_path;
static GString *output;
static guint index_number;

static void quoted(const char *text)
{
    g_string_append_c(output, '"');
    for (const unsigned char *p = (const unsigned char *)(text ? text : ""); *p; p++) {
        if (*p == '"' || *p == '\\')
            g_string_append_c(output, '\\');
        if (*p < 32)
            g_string_append_printf(output, "\\u%04x", *p);
        else
            g_string_append_c(output, *p);
    }
    g_string_append_c(output, '"');
}

static void inspect(GtkWidget *widget, int parent)
{
    guint index = index_number++;
    GtkAllocation allocation;
    gtk_widget_get_allocation(widget, &allocation);
    int x = 0, y = 0;
    gtk_widget_translate_coordinates(widget, gtk_widget_get_toplevel(widget), 0, 0, &x, &y);
    int root_x = 0, root_y = 0;
    GdkWindow *window = gtk_widget_get_window(gtk_widget_get_toplevel(widget));
    if (window)
        gdk_window_get_origin(window, &root_x, &root_y);
    char *tooltip = gtk_widget_get_tooltip_text(widget);
    if (index)
        g_string_append_c(output, ',');
    g_string_append_printf(output, "{\"parent\":%d,\"type\":", parent);
    quoted(G_OBJECT_TYPE_NAME(widget));
    g_string_append_printf(output, ",\"mapped\":%s,\"x\":%d,\"y\":%d,\"width\":%d,\"height\":%d",
                           gtk_widget_get_mapped(widget) ? "true" : "false",
                           x, y, allocation.width, allocation.height);
    g_string_append_printf(output, ",\"screen_x\":%d,\"screen_y\":%d", x + root_x, y + root_y);
    g_string_append(output, ",\"text\":");
    quoted(GTK_IS_LABEL(widget) ? gtk_label_get_text(GTK_LABEL(widget)) : "");
    g_string_append(output, ",\"tooltip\":");
    quoted(tooltip);
    g_string_append(output, ",\"classes\":[");
    GList *classes = gtk_style_context_list_classes(gtk_widget_get_style_context(widget));
    for (GList *item = classes; item; item = item->next) {
        if (item != classes)
            g_string_append_c(output, ',');
        quoted(item->data);
    }
    g_list_free(classes);
    g_string_append_printf(output, "],\"spacing\":%d}",
                           GTK_IS_BOX(widget) ? gtk_box_get_spacing(GTK_BOX(widget)) : -1);
    if (GTK_IS_CONTAINER(widget)) {
        GList *children = gtk_container_get_children(GTK_CONTAINER(widget));
        for (GList *item = children; item; item = item->next)
            inspect(item->data, index);
        g_list_free(children);
    }
    g_free(tooltip);
}

static gboolean poll_request(gpointer unused)
{
    (void)unused;
    char *request = NULL;
    if (!g_file_get_contents(request_path, &request, NULL, NULL))
        return G_SOURCE_CONTINUE;
    if (remove(request_path) != 0)
        g_error("Cannot consume workspace UI probe request");
    index_number = 0;
    output = g_string_new("{\"widgets\":[");
    GList *windows = gtk_window_list_toplevels();
    for (GList *item = windows; item; item = item->next)
        inspect(item->data, -1);
    g_list_free(windows);
    g_string_append(output, "]}");
    GError *error = NULL;
    if (!g_file_set_contents(response_path, output->str, -1, &error))
        g_error("Cannot write workspace UI probe response: %s", error->message);
    g_string_free(output, TRUE);
    g_free(request);
    return G_SOURCE_CONTINUE;
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    (void)argc;
    (void)argv;
    request_path = g_getenv("WORKSPACE_UI_REQUEST");
    response_path = g_getenv("WORKSPACE_UI_RESPONSE");
    if (!request_path || !response_path)
        g_error("Workspace UI probe needs private request/response paths");
    g_timeout_add(20, poll_request, NULL);
}
