# Generated by Django 3.0.8 on 2020-09-11 21:22

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('transmissions', '0004_transmission_planadmin_email'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='transmissionerroraggregate',
            options={'ordering': ['-run_date']},
        ),
        migrations.RenameField(
            model_name='transmissionerroraggregate',
            old_name='error_date',
            new_name='run_date',
        ),
    ]
