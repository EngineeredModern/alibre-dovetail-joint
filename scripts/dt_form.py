# Windows Forms presentation adapter for the Alibre manager (IronPython 2.7).
import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
from System import Action
from System.Drawing import Size, Font, FontStyle, Color
from System.Threading import ManualResetEvent
from System.Windows.Forms import (Form, Label, TextBox, ComboBox, Button,
    TableLayoutPanel, FlowLayoutPanel, Panel, DockStyle, ComboBoxStyle,
    AutoSizeMode, Padding, FormStartPosition, MessageBox, MessageBoxButtons,
    MessageBoxIcon, DialogResult, ColumnStyle, SizeType, AnchorStyles)


class ManagerForm(object):
    def __init__(self, options, changed, apply, defaults, cleanup, title, length_unit='in', unit_choices=None, unit_changed=None):
        self.options = options
        self.changed = changed
        self.apply = apply
        self.defaults = defaults
        self.cleanup = cleanup
        self.unit_changed = unit_changed
        self.controls = {}
        self.length_labels = {}
        self.muted = 0
        self.closed = ManualResetEvent(False)
        self.form = Form()
        self.form.Text = title
        self.form.ClientSize = Size(700, 810)
        self.form.MinimumSize = Size(620, 650)
        self.form.StartPosition = FormStartPosition.CenterScreen
        self.form.Font = Font('Segoe UI', 9)
        content = Panel()
        content.Dock = DockStyle.Fill
        content.AutoScroll = True
        self.form.FormClosed += self._closed
        self.table = TableLayoutPanel()
        self.table.Dock = DockStyle.Top
        self.table.AutoSize = True
        self.table.Padding = Padding(14)
        self.table.ColumnCount = 3
        self.table.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 34))
        self.table.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 46))
        self.table.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 20))
        content.Controls.Add(self.table)
        self.form.Controls.Add(content)
        self.row = 0
        self.capture_buttons = {}
        # Keep the former selector's value slot for compatibility with an
        # already-installed manager script while it is being upgraded.
        self.controls[1] = ComboBox()
        self._heading('Joint operation')
        self._input(0, 'Operation')
        self._unit_input(length_unit, unit_choices or [], unit_changed)
        self._input(2, 'Existing Joint')
        self._heading('Capture geometry')
        self._text('Select one item in the Alibre workspace, then press the matching Capture button. The label confirms each saved selection.')
        for index, label in [(3, 'Male Part'), (4, 'Female Part'),
                             (5, 'Shared Seam Edge'), (6, 'Shared Start Reference Edge')]:
            self._capture_input(index, label, ['male', 'female', 'seam', 'start'][index - 3])
        self._capture_input(8, options[8][0].replace(' (selected)', ''), 'limit')
        self.parameters_heading = self._heading('Parameters - %s, except angle' % length_unit)
        for index in [7, 9, 10, 11, 12, 13, 14, 15, 16]:
            label = options[index][0].replace(' (selected)', '')
            self._input(index, label, readonly=index in [8, 16])
        self.default_buttons = []
        buttons = FlowLayoutPanel()
        buttons.AutoSize = True
        buttons.Dock = DockStyle.Fill
        for label, action in [('Save Defaults', 'Save current values as defaults'),
                              ('Load Defaults', 'Load saved defaults'),
                              ('Restore Factory', 'Restore factory defaults')]:
            button = Button()
            button.Text = label
            button.AutoSize = True
            button.Click += self._default_handler(action)
            buttons.Controls.Add(button)
            self.default_buttons.append(button)
        self._right_wide(buttons)
        actions = FlowLayoutPanel()
        actions.AutoSize = True
        actions.Dock = DockStyle.Fill
        self.apply_button = Button()
        self.apply_button.Text = 'Create Joint'
        self.apply_button.Size = Size(220, 40)
        self.apply_button.Click += self._apply
        actions.Controls.Add(self.apply_button)
        self._right_wide(actions)
        bottom = Panel()
        bottom.Dock = DockStyle.Bottom
        bottom.Height = 46
        bottom.Padding = Padding(14, 4, 14, 4)
        self.status = Label()
        self.status.Text = 'Ready. Select geometry in Alibre to begin.'
        self.status.Font = Font(self.form.Font, FontStyle.Bold)
        self.status.AutoSize = True
        self.status.Anchor = AnchorStyles.Left
        self.status.Dock = DockStyle.Fill
        bottom.Controls.Add(self.status)
        self.form.Controls.Add(bottom)

    def _wide(self, control):
        self.table.Controls.Add(control, 0, self.row)
        self.table.SetColumnSpan(control, 3)
        self.row += 1

    def _text(self, text):
        label = Label()
        label.Text = text
        label.AutoSize = True
        label.MaximumSize = Size(550, 0)
        label.Margin = Padding(3, 6, 3, 8)
        self._wide(label)
        return label

    def _right_wide(self, control):
        self.table.Controls.Add(control, 1, self.row)
        self.table.SetColumnSpan(control, 2)
        self.row += 1

    def _heading(self, text):
        label = self._text(text)
        label.Font = Font(self.form.Font, FontStyle.Bold)
        label.ForeColor = Color.FromArgb(35, 75, 110)
        return label

    def _unit_input(self, length_unit, choices, changed):
        label = Label()
        label.Text = 'Display Units'
        label.AutoSize = True
        label.Anchor = AnchorStyles.Left
        label.Margin = Padding(3, 5, 6, 5)
        control = ComboBox()
        control.DropDownStyle = ComboBoxStyle.DropDownList
        for choice in choices:
            control.Items.Add(choice)
        control.SelectedIndex = 0 if control.Items.Count else -1
        if changed is not None:
            def handler(sender, event):
                if not self.muted:
                    changed(str(control.SelectedItem))
            control.SelectedIndexChanged += handler
        control.Dock = DockStyle.Fill
        self.table.Controls.Add(label, 0, self.row)
        self.table.Controls.Add(control, 1, self.row)
        self.table.SetColumnSpan(control, 2)
        self.row += 1
        self.unit_control = control

    def SetLengthUnit(self, unit):
        self.parameters_heading.Text = 'Parameters - %s, except angle' % unit
        for label in self.length_labels.values():
            base = label.Text.split(' (')[0]
            label.Text = '%s (%s)' % (base, unit)

    def _input(self, index, title, readonly=False):
        option = self.options[index]
        label = Label()
        label.Text = title
        label.AutoSize = True
        label.Anchor = AnchorStyles.Left
        label.Margin = Padding(3, 5, 6, 5)
        if index in [9, 10, 12, 13, 14, 15, 16]:
            self.length_labels[index] = label
        if isinstance(option[2], list):
            control = ComboBox()
            control.DropDownStyle = ComboBoxStyle.DropDownList
            for item in option[2]:
                control.Items.Add(item)
            control.SelectedIndex = int(option[3])
            control.SelectedIndexChanged += self._change_handler(index)
        else:
            control = TextBox()
            control.Text = str(option[2])
            control.ReadOnly = readonly
            control.TabStop = not readonly
            if not readonly:
                control.TextChanged += self._change_handler(index)
        control.Dock = DockStyle.Fill
        control.Margin = Padding(3, 3, 3, 3)
        control.AccessibleName = title
        self.controls[index] = control
        self.table.Controls.Add(label, 0, self.row)
        self.table.Controls.Add(control, 1, self.row)
        self.table.SetColumnSpan(control, 2)
        self.row += 1

    def _capture_input(self, index, title, key):
        option = self.options[index]
        label = Label()
        label.Text = title
        label.AutoSize = True
        label.Anchor = AnchorStyles.Left
        label.Margin = Padding(3, 5, 6, 5)
        control = TextBox()
        control.Text = str(option[2])
        control.ReadOnly = True
        control.TabStop = False
        control.Dock = DockStyle.Fill
        control.Margin = Padding(3)
        control.AccessibleName = title
        button = Button()
        button.Text = 'Capture'
        button.Dock = DockStyle.Fill
        button.AccessibleName = 'Capture ' + title
        button.Click += self._capture_handler(key, title)
        self.controls[index] = control
        self.capture_buttons[index] = button
        self.table.Controls.Add(label, 0, self.row)
        self.table.Controls.Add(control, 1, self.row)
        self.table.Controls.Add(button, 2, self.row)
        self.row += 1

    def _capture_handler(self, key, title):
        def handler(sender, event):
            try:
                choice_index = ['male', 'female', 'seam', 'start', 'limit'].index(key) + 1
                captured = self.changed(1, self.options[1][2][choice_index])
                if captured is False:
                    return
                self.RefreshOperation('Captured %s.' % title)
            except Exception as ex:
                self.ErrorDialog(str(ex), 'Sliding Dovetail')
        return handler

    def _change_handler(self, index):
        def handler(sender, event):
            if self.muted:
                return
            try:
                self.changed(index, self.GetInputValue(index))
                self.RefreshOperation()
            except Exception as ex:
                self.ErrorDialog(str(ex), 'Sliding Dovetail')
        return handler

    def _default_handler(self, action):
        def handler(sender, event):
            try:
                self.defaults(action)
            except Exception as ex:
                self.ErrorDialog(str(ex), 'Defaults')
        return handler

    def GetInputValue(self, index):
        if index == 17 or index == 1:
            return 0
        control = self.controls[index]
        if isinstance(control, ComboBox):
            return int(control.SelectedIndex)
        return control.Text

    def SetInputValue(self, index, value):
        if index == 17 or index == 1:
            return
        control = self.controls[index]
        self.muted += 1
        try:
            if isinstance(control, ComboBox):
                if isinstance(value, (int, long)):
                    control.SelectedIndex = int(value)
                else:
                    control.SelectedIndex = control.Items.IndexOf(str(value))
            else:
                control.Text = '' if value is None else str(value)
        finally:
            self.muted -= 1

    def SetStringList(self, index, values):
        self.muted += 1
        try:
            control = self.controls.get(index)
            if control is None:
                return
            control.Items.Clear()
            for value in values:
                control.Items.Add(value)
            control.SelectedIndex = 0 if control.Items.Count else -1
        finally:
            self.muted -= 1

    def DisableInput(self, index):
        control = self.controls.get(index)
        if control is not None:
            # Read-only geometry remains legible instead of disabled gray text.
            if not isinstance(control, TextBox) or not control.ReadOnly:
                control.Enabled = False

    def EnableInput(self, index):
        control = self.controls.get(index)
        if control is not None:
            control.Enabled = True

    def RefreshOperation(self, completed=None):
        operation = self.GetInputValue(0)
        mode = self.GetInputValue(7)
        self.apply_button.Text = ['Create Joint', 'Update Joint', 'Remove Joint'][operation]
        existing = self.controls[2]
        has_joint = existing.SelectedItem is not None and str(existing.SelectedItem).startswith('DT')
        capture_allowed = operation == 0
        for index in [3, 4, 5, 6]:
            self.capture_buttons[index].Enabled = capture_allowed
        self.capture_buttons[8].Enabled = capture_allowed and mode == 2
        for index, button in self.capture_buttons.items():
            text = self.controls[index].Text.strip()
            button.Text = 'Recapture' if text and text != 'Not captured' else 'Capture'
        if operation == 0:
            required = [(3, 'Male Part'), (4, 'Female Part'),
                        (5, 'Shared Seam Edge'), (6, 'Shared Start Reference Edge')]
            if mode == 2:
                required.append((8, 'Limit Geometry Face'))
            missing = [title for index, title in required
                       if not self.controls[index].Text.strip() or self.controls[index].Text == 'Not captured']
            self.apply_button.Enabled = not missing
            guidance = 'Ready to create the joint.' if not missing else 'Next: capture ' + missing[0] + '.'
        else:
            self.apply_button.Enabled = has_joint
            guidance = 'Choose an existing joint.' if not has_joint else 'Ready to %s this joint.' % (['create', 'update', 'remove'][operation])
        for button in self.default_buttons:
            button.Enabled = operation != 2
        if completed:
            guidance = completed + (' ' + guidance if guidance else '')
        self.status.ForeColor = Color.DarkGreen if completed else Color.Black
        self.status.Text = guidance

    def InfoDialog(self, message, title=None):
        self.status.ForeColor = Color.DarkGreen
        self.status.Text = message

    def ErrorDialog(self, message, title=None):
        self.status.ForeColor = Color.Firebrick
        self.status.Text = message
        MessageBox.Show(self.form, message, title or 'Sliding Dovetail',
                        MessageBoxButtons.OK, MessageBoxIcon.Error)

    def _apply(self, sender, event):
        operation = self.GetInputValue(0)
        if operation == 2:
            choice = str(self.controls[2].SelectedItem)
            if MessageBox.Show(self.form, 'Remove %s?' % choice, 'Remove Joint',
                               MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes:
                return
        self.apply_button.Enabled = False
        try:
            values = [self.GetInputValue(i) for i in range(len(self.options))]
            if self.apply(values):
                self.InfoDialog(['Joint created.', 'Joint updated.', 'Joint removed.'][operation])
        except Exception as ex:
            self.ErrorDialog(str(ex))
        finally:
            self.RefreshOperation()

    def _closed(self, sender, event):
        try:
            self.cleanup()
        finally:
            self.closed.Set()


def run_manager(parent, create):
    # Alibre host calls the script on a worker. Create and handle controls on
    # Alibre's UI thread, and keep the Python engine alive until the form closes.
    holder = []
    errors = []
    def show():
        try:
            adapter = create()
            holder.append(adapter)
            adapter.form.Show(parent)
        except Exception as ex:
            errors.append(ex)
    if parent.InvokeRequired:
        parent.Invoke(Action(show))
    else:
        raise Exception('The manager must be launched by the add-on worker.')
    if errors:
        raise errors[0]
    holder[0].closed.WaitOne()
    if not parent.IsDisposed:
        parent.Invoke(Action(lambda: None))
    holder[0].closed.Dispose()


