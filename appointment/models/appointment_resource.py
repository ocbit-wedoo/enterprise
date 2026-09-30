# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models
from odoo.tools.translate import html_translate


class AppointmentResource(models.Model):
    _name = "appointment.resource"
    _description = "Appointment Resource"
    _inherit = ["avatar.mixin", "resource.mixin"]
    _order = 'sequence,id'

    name = fields.Char('Name', related="resource_id.name", store=True, required=True, readonly=False)
    active = fields.Boolean('Active', related="resource_id.active", default=True, store=True, readonly=False)
    sequence = fields.Integer("Sequence", default=1, required=True,
        help="""The sequence dictates if the resource is going to be picked in higher priority against another resource
        (e.g. for 2 tables of 4, the lowest sequence will be picked first)""")
    company_id = fields.Many2one(default=False)
    resource_id = fields.Many2one(copy=False)
    resource_calendar_id = fields.Many2one(
        default=lambda self: (
            self.env.ref('appointment.appointment_default_resource_calendar', raise_if_not_found=False) or
            self.env.company.resource_calendar_id),
        help="If kept empty, the working schedule of the company set on the resource will be used")
    capacity = fields.Integer("Capacity", default=1, required=True,
        help="""Maximum amount of people for this resource (e.g. Table for 6 persons, ...)""")
    shareable = fields.Boolean("Shareable",
        help="""This allows to share the resource with multiple attendee for a same time slot (e.g. a bar counter)""")
    source_resource_ids = fields.Many2many(
        'appointment.resource', 'appointment_resource_linked_appointment_resource',
        'resource_id', 'linked_resource_id',
        domain="[('id', '!=', id)]",
        string='Source combination',
    )
    destination_resource_ids = fields.Many2many(
        'appointment.resource', 'appointment_resource_linked_appointment_resource',
        'linked_resource_id', 'resource_id',
        domain="[('id', '!=', id)]",
        string='Destination combination',
    )
    linked_resource_ids = fields.Many2many(
        'appointment.resource',
        compute='_compute_linked_resource_ids',
        inverse='_inverse_linked_resource_ids',
        domain="[('id', '!=', id)]",
        store=False,
        help="""List of resources that can be combined to handle a bigger demand.""")
    description = fields.Html("Description", translate=html_translate, sanitize_attributes=False)
    appointment_type_ids = fields.Many2many('appointment.type', string="Available in",
        relation="appointment_type_appointment_resource_rel",
        domain="[('schedule_based_on', '=', 'resources')]")

    _sql_constraints = [
        ('check_capacity', 'check(capacity >= 1)', 'The resource should have at least one capacity.')
    ]

    @api.depends('source_resource_ids', 'destination_resource_ids')
    def _compute_linked_resource_ids(self):
        """ Compute based on two sided many2many relationships. Resources used
        as source or destination of a relationship are combinable both ways. """
        for resource in self:
            linked = resource.source_resource_ids | resource.destination_resource_ids
            resource.linked_resource_ids = linked

    def _inverse_linked_resource_ids(self):
        """ Update combination. When having new combination, consider current
        record is always the source to simplify. When having to remove links
        remove from both source and destination relationships to be sure to
        really break the link. """
        for resource in self:
            actual_resources = resource.linked_resource_ids
            current_resources = resource.source_resource_ids | resource.destination_resource_ids
            new_resources = actual_resources - current_resources
            old_resources = current_resources - actual_resources
            resource.source_resource_ids = resource.source_resource_ids + new_resources - old_resources
            resource.destination_resource_ids = resource.destination_resource_ids - old_resources

    @api.depends('capacity')
    def _compute_display_name(self):
        """ Display the capacity of the resource next to its name if resource_manage_capacity is enabled """
        for resource in self:
            resource_name_capacity = f"{resource.name} (🪑{resource.capacity})"
            display_name = resource_name_capacity if resource.capacity > 1 else resource.name
            resource.display_name = display_name

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        return [dict(vals, name=self.env._("%s (copy)", resource.name)) for resource, vals in zip(self, vals_list)]

    def _get_best_combination_per_capacity(self, asked_capacity, capacity_info):
        """ Get best combination of resources for each capacity at least equal to asked_capacity.
        What is defined as 'best combination' for a given capacity is the one with lowest number
        of resources. Resources are considered in order of sequence. For each resource, we check
        combinations of that resource plus linked ones in self, using a dynamic programming approach
        to only keep the current best combinations in a dedicated structure.

        :param int asked_capacity: asked capacity for the appointment
        :param dict capacity_info: remaining capacity per resource
        :return list of tuples ((combination), total capacity): ordered by increasing capacity [
            ((1, 3), 8),
            ((1, 2, 3), 10),
        ]"""

        capacity_per_resource = {}
        for resource in self:
            capacity_per_resource[resource.id] = capacity_info.get(resource, {}).get('remaining_capacity', resource.capacity)

        def get_possible_capacities_for_resource(resource):
            """Get all possible capacities for a resource and its linked resources.
            Returns: dict mapping capacity -> first resource_ids combination that achieves it
            """
            # Collect all resources (main + linked) as dict: resource_id -> capacity
            linked_resources_dict = {resource.id: capacity_per_resource[resource.id]}
            for linked in resource.linked_resource_ids.sorted(key=lambda r: (r.sequence, r.id)) & self:
                linked_resources_dict[linked.id] = capacity_per_resource[linked.id]

            # Use Dynamic programming to find which capacities are achievable along with the resource combinations
            # combination_per_capacity[capacity] = tuple of resource_ids that achieve this capacity
            combination_per_capacity = {0: []}

            for resource_id, capacity in linked_resources_dict.items():
                # Iterate over existing capacities (make a list to avoid modification during iteration)
                existing_items = list(combination_per_capacity.items())

                for existing_cap, existing_resources in existing_items:
                    new_cap = existing_cap + capacity

                    # Only add if this capacity hasn't been achieved yet or is achieved with less resources
                    if (new_cap not in combination_per_capacity) or (len(existing_resources) + 1 < len(combination_per_capacity[new_cap])):
                        combination_per_capacity[new_cap] = existing_resources + [resource_id]

            return combination_per_capacity

        # Get capacity mappings for each top-level resource then merge into a global mapping
        global_capacity_map = {}
        for resource in self:
            resource_capacity_map = get_possible_capacities_for_resource(resource)

            for capacity, resource_ids in resource_capacity_map.items():
                # Only store if this capacity hasn't been seen yet or is achieved with less resources
                if (capacity not in global_capacity_map) or (len(resource_ids) < len(global_capacity_map[capacity])):
                    global_capacity_map[capacity] = resource_ids

        # Keep only if enough capacity
        candidate_combinations = {
            tuple(resource_ids): capacity
            for capacity, resource_ids in global_capacity_map.items()
            if capacity >= asked_capacity
        }

        # Return sorted by capacity
        return sorted(candidate_combinations.items(), key=lambda candidate_combination: candidate_combination[1])

    # remove in master
    def _get_filtered_possible_capacity_combinations(self, asked_capacity, capacity_info):
        """ Get combinations of resources with total capacity based on the capacity needed and the resources we want.
        :param int asked_capacity: asked capacity for the appointment
        :param dict main_resources_remaining_capacity: main resources available with the according total remaining capacity
        :param dict linked_resources_remaining_capacity: linked resources with the according remaining capacity
        :return list of tuple: e.g. [
            ((1, 3), 8),  # here the key: (1, 3) => combination of resource_ids; the value: 8 => remaining capacity for these resources
            ((1, 2, 3), 10),
        ]"""
        capacities = {}
        # get all capacities combination for the resources
        for resource in self:
            capacities.update(
                resource._get_possible_capacity_combinations(capacity_info))
        # filter capacities combination that can fit the asked capacity for a group of resources
        possible_capacities = {
            resource_ids: remaining_capacity
            for resource_ids, remaining_capacity in capacities.items()
            if remaining_capacity >= asked_capacity and all(resource_id in self.ids for resource_id in resource_ids)
        }
        # Sort possible_capacities by capacity and number of resources used in the combination
        # possible_capacity[0] = resource_ids and possible_capacity[1] = capacity
        return sorted(possible_capacities.items(), key=lambda possible_capacity: (possible_capacity[1], len(possible_capacity[0])))

    # remove in master
    def _get_possible_capacity_combinations(self, capacity_info):
        """ Return the possible capacity combination for the resource with all possible linked resources.
        :param dict main_resources_remaining_capacity: main resources available with the according total remaining capacity
        :param dict linked_resources_remaining_capacity: linked resources with the according remaining capacity
        :return: a dict where the key is a tuple of resource ids and the value is the total remaining capacity of these resources
        e.g. {
            (1): 4,
            (1, 2): 6,
            (1, 3): 8,
            (1, 2, 3): 10,
        }
        """
        self.ensure_one()
        resource_remaining_capacity = capacity_info.get(self, {}).get('remaining_capacity', self.capacity)
        capacities = {
            tuple(self.ids): resource_remaining_capacity,
        }
        for linked_resource in self.linked_resource_ids.sorted('sequence'):
            capacities_to_add = {}
            for resource_ids, capacity in capacities.items():
                new_resource_ids = set(resource_ids)
                new_resource_ids.add(linked_resource.id)
                linked_resource_capacity = capacity_info.get(linked_resource, {}).get('remaining_capacity', linked_resource.capacity)
                capacities_to_add.update({
                    tuple(sorted(new_resource_ids)): capacity + linked_resource_capacity,
                })
            capacities.update(capacities_to_add)
        return capacities

    def _prepare_resource_values(self, vals, tz):
        """ Override of the resource.mixin model method to force "material" as resource type for
        the resources created for our appointment.resources """
        resource_values = super()._prepare_resource_values(vals, tz)
        resource_values['resource_type'] = 'material'
        return resource_values
