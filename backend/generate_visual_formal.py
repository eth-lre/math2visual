import re
from lxml import etree
import math
import os
from IPython.display import SVG, display
from collections import defaultdict

error_message = ""

import re

def extract_visual_language(text):
    """
    Extracts the visual_language expression from the given text.
    It finds the last occurrence of 'visual_language:' and extracts everything after it.
    """
    keyword = "visual_language:"
    last_index = text.rfind(keyword)  # Find the last occurrence of 'visual_language:'

    if last_index != -1:
        return text[last_index:].strip()  # Extract and return everything after the last occurrence
    else:
        return None  # Return None if no match is found

def parse_dsl(dsl_str):
    operations_list = ["addition", "subtraction", "multiplication", "division", "surplus", "unittrans","area"]

    def split_entities(inside_str):
        """Safely splits entities or nested operations while balancing parentheses and square brackets."""
        entities = []
        balance_paren = 0
        balance_bracket = 0
        buffer = ""

        for char in inside_str:
            if char == "(":
                balance_paren += 1
            elif char == ")":
                balance_paren -= 1
            elif char == "[":
                balance_bracket += 1
            elif char == "]":
                balance_bracket -= 1

            if char == "," and balance_paren == 0 and balance_bracket == 0:
                entities.append(buffer.strip())
                buffer = ""
            else:
                buffer += char

        if buffer:
            entities.append(buffer.strip())

        return entities

    def recursive_parse(input_str):
        """Recursively parses operations and entities."""
        input_str = " ".join(input_str.strip().split())  # Clean spaces
        # func_pattern = r"(\w+)\((.*)\)"
        func_pattern = r"(\w+)\s*\((.*)\)"
        match = re.match(func_pattern, input_str)

        if not match:
            raise ValueError(f"DSL does not match the expected pattern: {input_str}")

        operation, inside = match.groups()  # Extract operation and content
        parsed_entities = []
        result_container = None

        # Safely split entities
        for entity in split_entities(inside):
            if any(entity.startswith(op) for op in operations_list):
                # Recognize and recurse into nested operations
                parsed_entities.append(recursive_parse(entity))
            else:
                # Parse as a basic entity
                entity_pattern = r"(\w+)\[(.*?)\]"
                entity_match = re.match(entity_pattern, entity)
                if not entity_match:
                    raise ValueError(f"Entity format is incorrect: {entity}")
                entity_name, entity_content = entity_match.groups()
                parts = [p.strip() for p in entity_content.split(',')]
                entity_dict = {"name": entity_name, "item": {}}
                for part in parts:
                    if ':' in part:
                        key, val = part.split(':', 1)
                        key, val = key.strip(), val.strip()
                        if key == "entity_quantity":
                            try:
                                entity_dict["item"]["entity_quantity"] = float(val)
                            except ValueError:
                                entity_dict["item"]["entity_quantity"] = 0.0  # Default to 0.0 if conversion fails
                        elif key == "entity_type":
                            entity_dict["item"]["entity_type"] = val
                        else:
                            entity_dict[key] = val
                
                # Check if this is a result_container
                if entity_name == "result_container":
                    result_container = entity_dict
                else:
                    parsed_entities.append(entity_dict)

        result = {"operation": operation, "entities": parsed_entities}
        if result_container:
            result["result_container"] = result_container

        return result

    return recursive_parse(dsl_str)


def render_svgs_from_data(output_file, resources_path, data):
    NS = "http://www.w3.org/2000/svg"
    svg_root = etree.Element("svg", nsmap={None: NS})

    def get_priority(op_name):
        """
        Returns a numeric priority for an operation name.
        Higher number => higher precedence.
        """
        if op_name in ("multiplication", "division"):
            return 2
        elif op_name in ("addition", "subtraction"):
            return 1
        else:
            # Default or fallback
            return 0

    def can_skip_same_precedence(parent_op, child_op):
        """
        Returns True if we can safely omit parentheses around the child sub-expression
        when the parent_op and child_op have the same precedence.
        - addition is associative
        - multiplication is associative
        - subtraction/division are not
        """
        # For addition: A + (B + C) == (A + B) + C
        # For multiplication: A * (B * C) == (A * B) * C
        # So skip brackets if both are addition or both are multiplication
        if parent_op == "addition" and child_op == "addition":
            return True
        if parent_op == "multiplication" and child_op == "multiplication":
            return True
        return False
    def extract_operations_and_entities(
        node,
        operations=None,
        entities=None,
        result_entities=None,
        parent_op=None,
        parent_container_name=None
    ):
        if operations is None:
            operations = []
        if entities is None:
            entities = []
        if result_entities is None:
            result_entities = []

        op = node.get("operation", "")

        # 1) If operation is "unittrans", just handle special logic and return
        if op == "unittrans":
            sub_ents = node.get("entities", [])
            if len(sub_ents) == 2:
                main_entity = sub_ents[0]
                unit_entity = sub_ents[1]
                # Example: store unit conversion info
                main_entity["unittrans_unit"]  = unit_entity["name"]
                main_entity["unittrans_value"] = unit_entity["item"]["entity_quantity"]
                entities.append(main_entity)
            return operations, entities, result_entities

        # 2) "comparison"? If not handled, raise or skip
        if op == "comparison":
            raise ValueError("We do not handle 'comparison' in this snippet")

        # 3) For normal operations (like addition, subtraction, multiplication, division)
        child_ents = node.get("entities", [])
        my_result  = node.get("result_container")

        if len(child_ents) < 2:
            # Not enough children to form an operation—skip
            return operations, entities, result_entities

        left_child  = child_ents[0]
        right_child = child_ents[1]

        # Determine this node's container_name (if any)
        if my_result and isinstance(my_result, dict):
            container_name = my_result.get("container_name")
        else:
            container_name = None

        # Decide if the entire sub-expression needs brackets
        need_brackets = False
        if parent_op is not None:
            parent_priority = get_priority(parent_op)
            current_priority = get_priority(op)

            if parent_priority > current_priority:
                # Strictly higher priority => definitely bracket
                need_brackets = True
            elif parent_priority == current_priority:
                print("container_name: ", container_name)
                print("parent_container_name: ", parent_container_name)
                if not can_skip_same_precedence(parent_op, op):
                    need_brackets = True

        # Track how many entities we already had before handling this sub-expression
        start_len = len(entities)

        # --- A) Handle left child ---
        if "operation" in left_child:
            extract_operations_and_entities(
                left_child,
                operations,
                entities,
                result_entities,
                parent_op=op,
                parent_container_name=container_name
            )
        else:
            # Leaf entity
            entities.append(left_child)

        # --- B) Record the current operation ---
        operations.append(op)

        # --- C) Handle right child ---
        if "operation" in right_child:
            extract_operations_and_entities(
                right_child,
                operations,
                entities,
                result_entities,
                parent_op=op,
                parent_container_name=container_name
            )
        else:
            # Leaf entity
            entities.append(right_child)

        # --- D) Mark brackets if needed ---
        if need_brackets:
            # The entire sub-expression is in entities[start_len:]
            if len(entities) > start_len:
                # Mark the first entity with bracket="left"
                entities[start_len]["bracket"] = "left"
                # Mark the last entity in this chunk with bracket="right"
                entities[-1]["bracket"] = "right"

        # --- E) If this is the top-level node (no parent_op), record the result entity ---
        if parent_op is None and my_result:
            if isinstance(my_result, dict):
                result_entities.append(my_result)

        return operations, entities, result_entities

    def extract_operations_and_entities_for_comparison(data):
        """
        Extract two sides (compare1 and compare2) from a top-level comparison.
        We assume data["operation"] == "comparison".
        Returns 6 separate lists:
            compare1_operations, compare1_entities, compare1_result_entities,
            compare2_operations, compare2_entities, compare2_result_entities
        """

        # Make sure data["entities"] exists and has 2 items
        if "entities" not in data or len(data["entities"]) < 2:
            # Malformed data => Return empty
            return [], [], [], [], [], []

        # The first item is compare1, the second is compare2
        compare1_data = data["entities"][0]
        compare2_data = data["entities"][1]

        # We'll parse each side with your original function
        # But that function might return 2 items or 3 items depending on 'unittrans'
        def safe_extract(data_piece):
            ret = extract_operations_and_entities(data_piece)
            if len(ret) == 2:
                # Means it was (operations, entities_list) => no result entities returned
                ops, ents = ret
                res = []
            else:
                # Means it was (operations, entities_list, result_entities_list)
                ops, ents, res = ret
            return ops, ents, res

        # 1) Parse compare1 side
        if isinstance(compare1_data, dict) and "operation" in compare1_data:
            compare1_ops, compare1_ents, compare1_res = safe_extract(compare1_data)
        else:
            # If it's just a single entity, no operation
            compare1_ops = []
            compare1_ents = [compare1_data]
            compare1_res = []

        # 2) Parse compare2 side
        if isinstance(compare2_data, dict) and "operation" in compare2_data:
            compare2_ops, compare2_ents, compare2_res = safe_extract(compare2_data)
        else:
            compare2_ops = []
            compare2_ents = [compare2_data]
            compare2_res = []

        # Return 6 separate lists
        return (
            compare1_ops, 
            compare1_ents, 
            compare1_res, 
            compare2_ops, 
            compare2_ents, 
            compare2_res
        )
    

    def handle_comparison(
        compare1_operations, compare1_entities, compare1_result_entities,
        compare2_operations, compare2_entities, compare2_result_entities,
        svg_root,
        resources_path,
        start_x=50,
        start_y=150):

        print("Handling comparison start")

        # We will store bounding boxes: (x, y, width, height) for each side
        entity_boxes = [None, None]

        # We'll iterate over the two "compare sides"
        comp_op_list = [compare1_operations, compare2_operations]
        comp_entity_list = [compare1_entities, compare2_entities]
        comp_result_container_list = [compare1_result_entities, compare2_result_entities]

        current_x = start_x
        current_y = start_y

        for i in range(2):
            operations_i = comp_op_list[i]
            entities_i = comp_entity_list[i]
            result_i = comp_result_container_list[i]
            svg_width = 0
            svg_height = 0

            try:
                created, w, h = handle_all_except_comparison(operations_i,
                                entities_i,
                                svg_root,
                                resources_path,
                                result_i,
                                start_x=current_x,
                                start_y=current_y)
            except:
                created = False
                print("Error in handle_all_except_comparison exception")
            svg_width, svg_height = int(float(w)), int(float(h))
            entity_boxes[i] = (current_x, current_y, svg_width, svg_height)

            current_x += svg_width + 110  # spacing
        print("Handling comparison created: ", created)
        # draw balance scale
        draw_balance_scale(svg_root, entity_boxes)

        return created, svg_root.attrib["width"], svg_root.attrib["height"]


    def draw_balance_scale(svg_root, entity_boxes):
        """
        Draws a balance scale below two figures whose bounding boxes are given
        by entity_boxes = [(x0, y0, w0, h0), (x1, y1, w1, h1)].
        The left plate has the same width as the first figure;
        the right plate has the same width as the second figure.
        The base and vertical stick are centered between both figures.

        Also updates the <svg> width and height so that the new elements are in view.
        """

        # Unpack bounding boxes for the two figures
        left_x,  left_y,  left_w,  left_h  = entity_boxes[0]
        right_x, right_y, right_w, right_h = entity_boxes[1]

        print("left_x, left_y, left_w, left_h: ", left_x, left_y, left_w, left_h)
        print("right_x, right_y, right_w, right_h: ", right_x, right_y, right_w, right_h)

        # Define how far below the bottom of the two figures to place the horizontal bar of the scale
        vertical_offset = 0

        # The lowest bottom among the two figures
        bottom_of_figures = max(left_h, right_h)

        # This will be the y-coordinate for the horizontal bar (and top of the vertical stick)
        bar_y = bottom_of_figures + vertical_offset

        # The center x between the two figures (we'll place the base & vertical pole here)
        center_x = ((left_x + left_w) + right_x) / 2.0

        # Create a <g> element to hold all parts of the balance scale
        balance_group = etree.SubElement(svg_root, 'g', id='balance-scale')

        

        ############################################################################
        

        

        ############################################################################
        # 4) Draw the left plate
        #    - The "top" of the plate is slightly below the bottom of the left figure
        #    - The width of the plate is the same as the width of the left figure
        ############################################################################
        left_plate_top_y =  bottom_of_figures + 10  # 10 px below left figure
        left_plate_left_x = left_x
        left_plate_right_x = left_x + left_w

        # We'll create a path that draws a line across the top, then a small curve back
        curve_offset = 90
        plate_mid_x = (left_plate_left_x + left_plate_right_x) / 2.0
        plate_bottom_y = left_plate_top_y + curve_offset

        # Our path: M L Q Z
        left_plate_path = (
            f"M {left_plate_left_x} {left_plate_top_y} "
            f"L {left_plate_right_x} {left_plate_top_y} "
            f"Q {plate_mid_x} {plate_bottom_y} {left_plate_left_x} {left_plate_top_y} Z"
        )

        etree.SubElement(
            balance_group, 'path',
            d=left_plate_path,
            fill="#f58d42",
            stroke="#f58d42",
            attrib={"stroke-width": "2"}
        )

      
        ############################################################################
        # 5) Draw the right plate
        #    - The top of the plate is slightly below the bottom of the right figure
        #    - The width of the plate is the same as the width of the right figure
        ############################################################################
        right_plate_top_y =  bottom_of_figures + 10
        right_plate_left_x = right_x
        right_plate_right_x = right_x + right_w

        plate_mid_x = (right_plate_left_x + right_plate_right_x) / 2.0
        plate_bottom_y = right_plate_top_y + curve_offset

        right_plate_path = (
            f"M {right_plate_left_x} {right_plate_top_y} "
            f"L {right_plate_right_x} {right_plate_top_y} "
            f"Q {plate_mid_x} {plate_bottom_y} {right_plate_left_x} {right_plate_top_y} Z"
        )

        etree.SubElement(
            balance_group, 'path',
            d=right_plate_path,
            fill="#f58d42",
            stroke="#f58d42",
            attrib={"stroke-width": "2"}
        )

        # The small vertical stick from the bar to the right plate
        right_vertical_plate_stick_width = 5
        right_vertical_plate_stick_height = (right_plate_top_y - bar_y)
        right_vertical_plate_stick_x = (right_x + right_w / 2.0) - (right_vertical_plate_stick_width / 2.0)
        right_vertical_plate_stick_y = bar_y

       

        # 2) Draw the horizontal bar
        ############################################################################
        # Let's make the bar span from just left of the left figure to just right of the right figure
        bar_margin = 20
        horizontal_bar_x = left_x + left_w/2
        horizontal_bar_y = plate_bottom_y - 15
        horizontal_bar_width = right_x + right_w/2 - (left_x + left_w/2)
        horizontal_bar_height = 20

        etree.SubElement(
            balance_group, 'rect',
            x=str(horizontal_bar_x),
            y=str(horizontal_bar_y),  # so it's centered at bar_y
            width=str(horizontal_bar_width),
            height=str(horizontal_bar_height),
            fill='#f58d42'
        )

        ############################################################################
        # 1) Draw the 2 vertical stick to support two plates
        ############################################################################
        # left stick
        vertical_stick_width = 10
        
        # The top of this pole is at bar_y, going downward
        left_vertical_stick_x = horizontal_bar_x
        vertical_stick_y = plate_bottom_y - 50
        vertical_stick_height = horizontal_bar_y - vertical_stick_y
        # vertical_stick_y - horizontal_bar_y

        etree.SubElement(
            balance_group, 'rect',
            x=str(left_vertical_stick_x),
            y=str(vertical_stick_y),
            width=str(vertical_stick_width),
            height=str(vertical_stick_height),
            fill='#f58d42'
        )

        # right stick
        vertical_stick_width = 10
        right_vertical_stick_x = horizontal_bar_x + horizontal_bar_width


        etree.SubElement(
            balance_group, 'rect',
            x=str(right_vertical_stick_x),
            y=str(vertical_stick_y),
            width=str(vertical_stick_width),
            height=str(vertical_stick_height + horizontal_bar_height),
            fill='#f58d42'
        )
        ############################################################################
        # 1) Draw the central stick
        ############################################################################
        # vertical_stick_width = 10
        # vertical_stick_height = 50
        # # The top of this pole is at bar_y, going downward
        # vertical_stick_x = center_x - (vertical_stick_width / 2.0)
        # vertical_stick_y = bar_y - vertical_stick_height
        central_stick_x = horizontal_bar_x + horizontal_bar_width/2
        central_stick_height = 100
        central_stick_width = 20
        etree.SubElement(
            balance_group, 'rect',
            x=str(central_stick_x),
            y=str(horizontal_bar_y),
            width=str(central_stick_width),
            height=str(central_stick_height),
            fill='#f58d42'
        )

        ############################################################################
        # 3) Draw the base (small rectangle under the vertical pole)
        ############################################################################

        
        base_y = horizontal_bar_y + central_stick_height
        base_width = 2 * central_stick_width 
        base_height = 50
        base_x = central_stick_x - base_width/4
        etree.SubElement(
            balance_group, 'rect',
            x=str(base_x),
            y=str(base_y),
            width=str(base_width),
            height=str(base_height),
            fill='#f58d42'
        )
        ###########################################################################
        # 6) Update the SVG's width/height so the newly added scale is visible
        ############################################################################
       
        # Force them to be integers for cleanliness
        
        svg_root.attrib["height"] = str(base_y + base_height + 20)

    def update_container_types_optimized(entities, result_entities):
        """
        Update the container_type for entities in the same group (by container_type)
        when there is more than one unique container_name. In addition, treat the last
        item of result_entities as one of the entities (by reference) so that its
        container_type is updated if necessary.
        
        If there is only one unique container_name for a given container_type,
        leave it unchanged. Otherwise, assign a unique container_type value for each
        container_name within that group.
        
        Parameters:
        entities (list): List of entity dictionaries.
        result_entities (list): List of result entity dictionaries.
            If non-empty, the last item will be processed along with entities.
        
        Returns:
        A tuple (entities, result_entities) where:
            - entities: the original list (with updated container_type values)
            - result_entities: the modified list (the last item updated as needed)
        """
        # Create a temporary combined list from entities.
        combined = entities[:]  # shallow copy; dictionary objects remain the same
        if result_entities:
            # Append the last result entity (by reference) to combined.
            combined.append(result_entities[-1])
        
        # Group combined items by the original container_type.
        entity_type_to_entities = defaultdict(list)
        for entity in combined:
            entity_type_to_entities[entity['container_type']].append(entity)
        
        # Iterate through each container_type group.
        for container_type, group in entity_type_to_entities.items():
            # Group further by container_name.
            name_to_entities = defaultdict(list)
            for entity in group:
                name_to_entities[entity['container_name']].append(entity)
            
            # If there is only one unique container_name in this group, nothing to change.
            if len(name_to_entities) <= 1:
                continue
            
            # Initialize modification index.
            modification_index = 1  # for the first unique container_name, leave container_type unchanged.
            
            # Iterate through unique container_name groups in insertion order.
            for name, ent_group in name_to_entities.items():
                if modification_index == 1:
                    # Use the original container_type for the first group.
                    new_entity_type = container_type
                else:
                    new_entity_type = container_type + "-" + str(modification_index)
                # Set the container_type for all entities in this group.
                for entity in ent_group:
                    entity['container_type'] = new_entity_type
                modification_index += 1

        return entities, result_entities
    
   
    def handle_all_except_comparison(operations, entities, svg_root, resources_path,result_entities,start_x=50, start_y=100):
        global error_message
        # Constants
        UNIT_SIZE = 40
        APPLE_SCALE = 0.75
        ITEM_SIZE = int(UNIT_SIZE * APPLE_SCALE)
        ITEM_PADDING = int(UNIT_SIZE * 0.25)
        BOX_PADDING = UNIT_SIZE
        OPERATOR_SIZE = 30
        MAX_ITEM_DISPLAY = 10
        MARGIN = 50
        if any("unittrans_unit" in entity for entity in entities):   #刀
            ITEM_SIZE = 3 * ITEM_SIZE


        # Extract quantities and entity_types
        quantities = [e["item"].get("entity_quantity", 0) for e in entities]
        entity_types = [e["item"].get("entity_type", "") for e in entities]

        any_multiplier = any(t == "multiplier" for t in entity_types)
        any_above_20 = any(q > MAX_ITEM_DISPLAY for q in quantities)

        # Determine entity layout entity_type first
        for e in entities:
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "")
            container = e.get("container_type", "")
            attr = e.get("attr_entity_type", "")

            
            if t == "multiplier":
                e["layout"] = "multiplier"
            elif q > MAX_ITEM_DISPLAY or q % 1 != 0:
                e["layout"] = "large"
            else:
                if "row" in [container, attr]:
                    e["layout"] = "row"
                elif "column" in [container, attr]:
                    e["layout"] = "column"
                else:
                    e["layout"] = "normal"

        # Focus on normal layout entities
        normal_entities = [e for e in entities if e["layout"] == "normal"]

        # Compute global layout for normal entities:
        # 1. Find the largest entity_quantity among normal layout entities
        if normal_entities:
            largest_normal_q = max(e["item"].get("entity_quantity",0) for e in normal_entities)
        else:
            largest_normal_q = 1

        # 2. Compute global max_cols and max_rows for this largest normal q
        if largest_normal_q > 0:
            max_cols = int(math.ceil(math.sqrt(largest_normal_q)))
            max_rows = (largest_normal_q + max_cols - 1) // max_cols
        else:
            max_cols, max_rows = 1, 1

        # Assign these global cols and rows to all normal entities
        for e in normal_entities:
            e["cols"] = max_cols
            e["rows"] = max_rows

        # For row/column entities and large entities, compute cols/rows individually
        unit_trans_padding = 0
        for e in entities:
            if e["layout"] == "large":
                # Large scenario doesn't rely on cols/rows for layout calculation (just 1x1 effectively)
                e["cols"] = 1
                e["rows"] = 1
            elif e["layout"] == "row":
                q = e["item"].get("entity_quantity", 0)
                e["cols"] = q if q > 0 else 1
                e["rows"] = 1
            elif e["layout"] == "column":
                q = e["item"].get("entity_quantity", 0)
                e["cols"] = 1
                e["rows"] = q if q > 0 else 1
            elif e["layout"] == "multiplier":
                e["cols"] = 1
                e["rows"] = 1

            if e.get("unittrans_unit", ""):
                unit_trans_padding = 50
            
            # normal layout already assigned

        # Compute normal box size using global max_cols and max_rows
        normal_box_width = max_cols * (ITEM_SIZE + ITEM_PADDING) + BOX_PADDING
        normal_box_height = max_rows * (ITEM_SIZE + ITEM_PADDING + unit_trans_padding) + BOX_PADDING

        # Large scenario box dimension
        largest_q = max(quantities) if quantities else 1
        q_str = str(largest_q)
        text_width = len(q_str)*20
        # large_total_width = text_width + 10 + UNIT_SIZE + 10 + UNIT_SIZE  #刀
        large_total_width = ITEM_SIZE * 4
        large_box_width = large_total_width + BOX_PADDING
        # large_box_height = UNIT_SIZE + BOX_PADDING*2 + unit_trans_padding
        large_box_height = ITEM_SIZE * 4 + BOX_PADDING

        # Decide reference box size if large scenario or multiplier
        if any_multiplier or any_above_20:
            ref_box_width = max(normal_box_width, large_box_width)
            ref_box_height = max(normal_box_height, large_box_height)
        else:
            ref_box_width = normal_box_width
            ref_box_height = normal_box_height

        # Compute final box size for each entity based on layout
        def compute_entity_box_size(e):
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "")
            layout = e["layout"]
            unit_trans_padding = 0
            

            if layout == "multiplier":
                # Multiplier: minimal width, same height as ref to align
                return (UNIT_SIZE * 2, ref_box_height )
            if layout == "large":
                return (large_box_width, large_box_height )
            elif layout == "normal":
                # Use global normal box size
                return (normal_box_width, normal_box_height)
            elif layout == "row":
                cols = e["cols"] # q items in a row
                rows = 1
                w = cols*(ITEM_SIZE+ITEM_PADDING)+BOX_PADDING
                h = rows*(ITEM_SIZE+ITEM_PADDING)+BOX_PADDING
                return (w, h)
            elif layout == "column":
                cols = 1
                rows = e["rows"] 
                w = cols*(ITEM_SIZE+ITEM_PADDING)+BOX_PADDING
                h = rows*(ITEM_SIZE+ITEM_PADDING)+BOX_PADDING
                return (w, h)
            # fallback
            return (normal_box_width, normal_box_height)

        for e in entities:
            w,h = compute_entity_box_size(e)
            e["planned_width"] = w
            if e.get("unittrans_unit", ""):
                e["planned_height"] = h + 50
            else:
                e["planned_height"] = h

            # print('e["planned_width"]', e["planned_width"])
            # print('e["planned_height"]', e["planned_height"])


        # Position planning 
        # start_x, start_y = 50, 100
        operator_gap = e_gap = eq_gap = qmark_gap = 20

        # Initialize the starting point for the first entity
        current_x = start_x
        current_y = start_y
        box_y = start_y
        position_box_y = 0
        # Iterate through the entities and operators
        for i, entity in enumerate(entities):
            # Set position for the current entity
            entity["planned_x"] = current_x
            if entity.get("unittrans_unit", ""):
                entity["planned_y"] = current_y 
                entity["planned_box_y"] = current_y - 50
                box_y = current_y - 50
            else:
                entity["planned_y"] = current_y
                entity["planned_box_y"] = current_y
                box_y = current_y
            if i == 0:
                position_box_y = box_y
            # Update the rightmost x-coordinate of the current entity
            e_right = current_x + entity["planned_width"]
            if operations and i < len(operations):
                # Position the operator
                operator_x = e_right + operator_gap
                operator_y = position_box_y + (entities[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2)
                
                operations[i]["planned_x"] = operator_x
                operations[i]["planned_y"] = operator_y
                print("operations[i][planned_y]: ",operations[i]["planned_y"])
                print('operator, box_y: ',box_y)
                print('operator entities[0]["planned_height"]: ',entities[0]["planned_height"])

                # Update the x-coordinate for the next entity
                current_x = operator_x + OPERATOR_SIZE + e_gap
            else:
                # For the last entity, just update the x-coordinate for spacing
                current_x = e_right + e_gap
        # Position the equals sign
        eq_x = current_x + eq_gap
        eq_y = position_box_y + (entities[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2)
        print('first eq_y: ',eq_y)
        print('eq y, box_y: ',box_y)
        print('eq y entities[0]["planned_height"]: ',entities[0]["planned_height"])
        
        # Position the question mark
        qmark_x = eq_x + 30 + qmark_gap
        qmark_y = position_box_y + (entities[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2)-15






        max_x, max_y = 0,0
        def update_max_dimensions(x_val, y_val):
            nonlocal max_x, max_y
            if x_val > max_x:
                max_x = x_val
            if y_val > max_y:
                max_y = y_val
            print('max_x, max_y: ',max_x, max_y)

       
        def embed_svg(file_path, x, y, width, height):
            global error_message, _svg_directory_cache
            if not os.path.exists(file_path):
                print("SVG file not found:", file_path)
                # Get the directory and base name from the file_path
                dir_path = os.path.dirname(file_path)
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                
                # Use cached candidate list if available
                if dir_path in _svg_directory_cache:
                    candidate_files = _svg_directory_cache[dir_path]
                else:
                    candidate_files = [f for f in os.listdir(dir_path) if f.lower().endswith(".svg")]
                    _svg_directory_cache[dir_path] = candidate_files

                # Build candidate paths
                candidate_paths = [os.path.join(dir_path, f) for f in candidate_files]
                
                found_path = None
                
                # Helper: Try a candidate name against all files (case-insensitive)
                def try_candidate(name):
                    for candidate in candidate_paths:
                        candidate_base = os.path.splitext(os.path.basename(candidate))[0]
                        if candidate_base.lower() == name.lower():
                            return candidate
                    return None

                # 1. Try exact match using the given base_name
                found_path = try_candidate(base_name)
                
                # 2. Try using singular and plural forms using inflect
                if not found_path:
                    singular_form = p.singular_noun(base_name) or base_name
                    plural_form = p.plural_noun(base_name) or base_name
                    for mod_name in (plural_form, singular_form):
                        found_path = try_candidate(mod_name)
                        if found_path:
                            break

                # 3. If a hyphen exists, try matching only the part after the hyphen (and its variants)
                if not found_path and "-" in base_name:
                    after_hyphen = base_name.split("-")[-1]
                    singular_after = p.singular_noun(after_hyphen) or after_hyphen
                    plural_after = p.plural_noun(after_hyphen) or after_hyphen
                    for mod_name in (after_hyphen, plural_after, singular_after):
                        found_path = try_candidate(mod_name)
                        if found_path:
                            break

                # 4. As a last resort, use fuzzy matching to select the best candidate.
                if not found_path:
                    candidate_bases = [os.path.splitext(f)[0] for f in candidate_files]
                    close_matches = difflib.get_close_matches(base_name, candidate_bases, n=1, cutoff=0.6)
                    if close_matches:
                        match = close_matches[0]
                        found_path = try_candidate(match)
                
                if found_path:
                    file_path = found_path
                    print("Found alternative SVG file:", file_path)
                else:
                    print("SVG file not found using alternative search:", file_path)
                    error_message = f"SVG file not found using alternative search: {file_path}"
                    raise FileNotFoundError(f"SVG file not found: {file_path}")

            # If file_path exists now, parse and update attributes.
            tree = etree.parse(file_path)
            root = tree.getroot()
            root.attrib["x"] = str(x)
            root.attrib["y"] = str(y)
            root.attrib["width"] = str(width)
            root.attrib["height"] = str(height)
            update_max_dimensions(x + width, y + height)
            return root
        
        def get_figure_svg_path(attr_entity_type):
            if attr_entity_type:
                return os.path.join(resources_path, f"{attr_entity_type}.svg")
            return None

    
        def embed_top_figures_and_text(parent, box_x, box_y, box_width, container_type, container_name, attr_entity_type, attr_name):
            print("calling embed_top_figures_and_text")
            items = []
            show_something = container_name or container_type or attr_name or attr_entity_type
            print("container_type", container_type)
            if not show_something:
                items.append(("text", ""))
            else:
                # Check if container_type exists and the corresponding SVG file is valid
                if container_type:
                    figure_path = get_figure_svg_path(container_type)
                    if figure_path and os.path.exists(figure_path):
                        items.append(("svg", container_type))
                    else:
                        print(f"SVG for container_type '{container_type}' does not exist. Ignoring container_type.")
                
                if container_name:
                    items.append(("text", container_name))

                if attr_entity_type and attr_name:
                    figure_path = get_figure_svg_path(attr_entity_type)
                    if figure_path and os.path.exists(figure_path):
                        items.append(("svg", attr_entity_type))
                    items.append(("text", attr_name))

            # Simulate the needed width for all items
            item_positions = []
            total_width = 0
            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    width = UNIT_SIZE
                else:
                    # Calculate text width based on length
                    width = len(v) * 7  # Approximate width per character at font-size 15px
                item_positions.append((t, v, width))
                total_width += width
                if idx < len(items) - 1:
                    total_width += 10  # Add spacing between items

            # Calculate the starting X position to center all items
            start_x = box_x + (box_width - total_width) / 2
            center_y = box_y - UNIT_SIZE - 5

            group = etree.SubElement(parent, "g")
            current_x = start_x

            for idx, (t, v, width) in enumerate(item_positions):
                if t == "svg":
                    figure_path = get_figure_svg_path(v)
                    if figure_path and os.path.exists(figure_path):
                        svg_el = embed_svg(figure_path, x=current_x, y=center_y, width=UNIT_SIZE, height=UNIT_SIZE)
                        # Append the returned svg element to the group
                        group.append(svg_el)
                    current_x += width
                else:
                    # text_x = current_x + (width / 2)  # Center the text properly
                    text_x = current_x
                    text_y = center_y + (UNIT_SIZE / 2)
                    text_element = etree.SubElement(group, "text", x=str(text_x), y=str(text_y),
                                                    style="font-size: 15px;", dominant_baseline="middle", text_anchor="middle")
                    text_element.text = v
                    current_x += width

                if idx < len(items) - 1:
                    current_x += 10

        

        def draw_entity(e):
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "apple")
            container_name = e.get("container_name", "").strip()
            container_type = e.get("container_type", "").strip()
            attr_name = e.get("attr_name", "").strip()
            attr_entity_type = e.get("attr_entity_type", "").strip()

            # UnitTrans-specific attributes
            unittrans_unit = e.get("unittrans_unit", "")
            unittrans_value = e.get("unittrans_value", None)

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            layout = e["layout"]
            cols = e["cols"]
            rows = e["rows"]

    
            q = float(q)
            if layout == "multiplier":
                if q.is_integer():
                    q_str = str(int(q))  # Convert to integer
                else:
                    q_str = str(q)  # Keep as is
                text_x = x + w/2
                # Adjust text_y to align with operator
                text_y = position_box_y+ (entities[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2) + 34
                print('multiplier text y: ', text_y)
                text_element = etree.SubElement(svg_root, "text", x=str(text_x), y=str(text_y),
                                                style="font-size: 50px;", dominant_baseline="middle")
                text_element.text = q_str
                update_max_dimensions(text_x + len(q_str)*30, text_y + 50)
                print('2 update_max_dimensions: ',text_x + len(q_str)*30, text_y + 50)
                return
            # Draw box
            etree.SubElement(svg_root, "rect", x=str(x), y=str(box_y),
                            width=str(w), height=str(h), stroke="black", fill="none")
            
            # Draw bracket
            bracket_y = position_box_y + (entities[0]["planned_height"] / 2) + 13
            try: 
                if e.get("bracket") == "left":
                    
                    text_element = etree.SubElement(svg_root, "text",
                                                                    x=str(x-20), #刀
                                                                    y=str(bracket_y),  # Center text vertically
                                                                    style="font-size: 60px;",
                                                                    text_anchor="middle",  # Center align text
                                                                    dominant_baseline="middle")  # Center align text vertically
                    text_element.text = "("
                elif e.get("bracket") == "right":
                    print('right bracket true')
                    operator_y = position_box_y + (entities[0]["planned_height"] * 1.2 / 2)
                    text_element = etree.SubElement(svg_root, "text",
                                                            x=str(x+w), #刀
                                                            y=str(bracket_y),  # Center text vertically
                                                            style="font-size: 60px;",
                                                            text_anchor="middle",  # Center align text
                                                            dominant_baseline="middle")
                    text_element.text = ")"
                    print('right bracket true sucess')
            except:
                print("No bracket")

            # y + h 
            update_max_dimensions(x + w, y + h)
            print('3 update_max_dimensions: ',x + w, y + h)

            # Embed text or figures at the top
            embed_top_figures_and_text(svg_root, x, box_y, w, container_type, container_name, attr_entity_type, attr_name)


            if layout == "large":
                # print('ITEM_SIZE', ITEM_SIZE)
                # if unittrans_unit and unittrans_value is not None:
                #     global ITEM_SIZE
                #     ITEM_SIZE = ITEM_SIZE / 2
                # Large scenario
                q = float(q)
                if q.is_integer():
                    q_str = str(int(q))  # Convert to integer
                else:
                    q_str = str(q)  # Keep as is
                tw = len(q_str)*20
                # total_width = tw + 10 + UNIT_SIZE + 10 + UNIT_SIZE
                # print('item_size', ITEM_SIZE)
                total_width = ITEM_SIZE * 4
                # print('item_size', ITEM_SIZE)
                start_x_line = x + (w - total_width)/2
                svg_x = start_x_line
                center_y_line = y + (h - UNIT_SIZE)/2
                svg_y = center_y_line - 1.5 * ITEM_SIZE
                svg_y = y + ITEM_PADDING
                text_y = y + ITEM_PADDING + 2.4 * ITEM_SIZE
                text_x = svg_x+ITEM_SIZE*1.

                
                # Add item SVG
                item_svg_path = os.path.join(resources_path, f"{t}.svg")
                svg_root.append(embed_svg(item_svg_path, x=svg_x, y= svg_y, width=ITEM_SIZE * 4  , height=ITEM_SIZE * 4)) # 
                
                # Add entity_quantity text
                if unittrans_unit and unittrans_value is not None:
                    text_element = etree.SubElement(svg_root, "text", x=str(text_x),
                                                    y=str(text_y),
                                                    style="font-size: 100px; fill: white; font-weight: bold; stroke: black; stroke-width: 2px;", dominant_baseline="middle")
                else:
                    text_element = etree.SubElement(svg_root, "text", x=str(text_x),
                                                    y=str(text_y),
                                                    style="font-size: 45px; fill: white; font-weight: bold; stroke: black; stroke-width: 2px;", dominant_baseline="middle")
                text_element.text = q_str
                update_max_dimensions(start_x_line + tw, center_y_line + 40)
                print('4 update_max_dimensions: ',start_x_line + tw, center_y_line + 40)

                if unittrans_unit and unittrans_value is not None:
                    # Define circle position
                    circle_radius = 30
                    unit_trans_padding = 50
                    # circle_center_x = item_x + ITEM_SIZE -5 
                    # item_x = x + BOX_PADDING / 2 + ITEM_SIZE + ITEM_PADDING
                    item_x = start_x_line
                    item_y = y + BOX_PADDING / 2 + ITEM_SIZE + ITEM_PADDING + unit_trans_padding
                    circle_center_x = x + 2 * ITEM_SIZE
                    circle_center_y = svg_y - circle_radius # Above the top-right corner of the item

                    # Add purple circle
                    etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                                    r=str(circle_radius), fill="#BBA7F4")

                    # Add text inside the circle
                    # plural_suffix = "s" if unittrans_value > 1 else ""  # Add 's' if value is plural
                    # unittrans_text = f"{unittrans_value} {unittrans_unit}{plural_suffix}"
                    unittrans_text = f"{unittrans_value}"
                 
                    #     unittrans_text = f"{int(unittrans_value)}"  # Convert to integer
                    # else:
                    #     unittrans_text = f"{unittrans_value}"  # Keep as is
                    text_element = etree.SubElement(svg_root, "text",
                                                    x=str(circle_center_x-15), #
                                                    y=str(circle_center_y + 5),  # Center text vertically
                                                    style="font-size: 15px;",
                                                    text_anchor="middle",  # Center align text
                                                    dominant_baseline="middle")  # Center align text vertically
                    text_element.text = unittrans_text
            else:
                # Use global cols and rows for normal, row, column layouts
                if layout in ["normal", "row", "column"]:
                    item_svg_path = os.path.join(resources_path, f"{t}.svg")
                    for i in range(int(q)):
                        row = i // cols
                        col = i % cols
                        unit_trans_padding = 0
                        if unittrans_unit and row != 0:
                            unit_trans_padding = 50
                        item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                        item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING + unit_trans_padding) 

                        # Draw the item
                        svg_root.append(embed_svg(item_svg_path, x=item_x, y=item_y, width=ITEM_SIZE, height=ITEM_SIZE))
                        
                        # If unittrans_unit exists, add the purple circle
                        if unittrans_unit:
                            # Define circle position
                            circle_radius = 30
                            # circle_center_x = item_x + ITEM_SIZE -5 
                            circle_center_x = item_x + ITEM_SIZE/2
                            circle_center_y = item_y - circle_radius # Above the top-right corner of the item

                            # Add purple circle
                            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                                            r=str(circle_radius), fill="#BBA7F4")

                            # Add text inside the circle
                            # plural_suffix = "s" if unittrans_value > 1 else ""  # Add 's' if value is plural
                            # unittrans_text = f"{unittrans_value} {unittrans_unit}{plural_suffix}"
                            unittrans_text = f"{unittrans_value}"
                         
                            #     unittrans_text = f"{int(unittrans_value)}"  # Convert to integer
                            # else:
                            #     unittrans_text = f"{unittrans_value}"  # Keep as is
                            text_element = etree.SubElement(svg_root, "text",
                                                            x=str(circle_center_x-15), #
                                                            y=str(circle_center_y + 5),  # Center text vertically
                                                            style="font-size: 15px;",
                                                            text_anchor="middle",  # Center align text
                                                            dominant_baseline="middle")  # Center align text vertically
                            text_element.text = unittrans_text


            


        # Draw entities
        for entity in entities:  # Assuming exactly two entities
            print("entity: ", entity)
            draw_entity(entity)

        # Draw operator
        if operations:
            operator_svg_mapping = {
                "surplus": "division",  # Map 'surplus' to 'subtraction.svg'
                "area": "multiplication",
                "default": "addition"      # Fallback default operator
            }
            for operator in operations:
            # Get the mapped SVG entity_type for the operator
                operator_entity_type = operator['entity_type']
                mapped_operator_entity_type = operator_svg_mapping.get(operator_entity_type, operator_entity_type)  # Fallback to itself if not in mapping
                
                # Determine the SVG file path
                operator_svg_path = os.path.join(resources_path, f"{mapped_operator_entity_type}.svg")
                
                # Fallback to the default operator SVG if the file does not exist
                if not os.path.exists(operator_svg_path):
                    fallback_entity_type = operator_svg_mapping["default"]
                    operator_svg_path = os.path.join(resources_path, f"{fallback_entity_type}.svg")
                
                # Embed the operator SVG at its planned position
                svg_root.append(
                    embed_svg(
                        operator_svg_path,
                        x=operator["planned_x"],
                        y=operator["planned_y"],
                        width=OPERATOR_SIZE,
                        height=OPERATOR_SIZE
                    )
                )
                print('operator[planned_y]: ', operator['planned_y'])



        # Draw equals
        equals_svg_path = os.path.join(resources_path, "equals.svg")
        if not os.path.exists(equals_svg_path):
            equals_svg_path = os.path.join(resources_path, "equals_default.svg")  # Fallback if necessary
        svg_root.append(embed_svg(equals_svg_path, x=eq_x, y=eq_y, width=30, height=30))
        print('eq_y: ', eq_y)

        last_x_point = 0
        # Draw question mark
        if operations and operations[-1]["entity_type"] == "surplus":
            # Draw the first question mark
            question_mark_svg_path = os.path.join(resources_path, "question.svg")
            if not os.path.exists(question_mark_svg_path):
                question_mark_svg_path = os.path.join(resources_path, "question_default.svg")  # Fallback if necessary
            svg_root.append(embed_svg(question_mark_svg_path, x=qmark_x, y=qmark_y, width=60, height=60))

            # Calculate position for the "with remainder" text
            text_x = qmark_x + 70  # Adjust spacing to place text after the first question mark
            text_y = qmark_y + 35  # Vertically aligned with the question mark

            # Add the "with remainder" text
            text_element = etree.SubElement(
                svg_root,
                "text",
                x=str(text_x),
                y=str(text_y),
                style="font-size: 15px;",
                dominant_baseline="middle"
            )
            text_element.text = "with remainder"

            # Calculate position for the second question mark
            second_qmark_x = text_x + 100  # Adjust based on text width (approximate)
            second_qmark_y = qmark_y

            # Draw the second question mark
            svg_root.append(embed_svg(question_mark_svg_path, x=second_qmark_x, y=second_qmark_y, width=60, height=60))
            last_x_point = second_qmark_x + 60
        else:
            # Default case: draw a single question mark
            question_mark_svg_path = os.path.join(resources_path, "question.svg")
            if not os.path.exists(question_mark_svg_path):
                question_mark_svg_path = os.path.join(resources_path, "question_default.svg")  # Fallback if necessary
            svg_root.append(embed_svg(question_mark_svg_path, x=qmark_x, y=qmark_y, width=60, height=60))
            last_x_point = qmark_x + 60


        # Update SVG size
        final_width = max_x + MARGIN
        final_height = max_y + MARGIN
        svg_root.attrib["width"] = str(final_width)
        svg_root.attrib["height"] = str(final_height)

        width = last_x_point - start_x

        # return True, width, svg_root.attrib["height"]
        return True, str(float(svg_root.attrib["width"]) - start_x), svg_root.attrib["height"]



    # main function:
    created = False
    if data.get('operation') == "comparison":
        (
        compare1_operations, 
        compare1_entities, 
        compare1_result_entities,
        compare2_operations, 
        compare2_entities, 
        compare2_result_entities
        ) = extract_operations_and_entities_for_comparison(data)

        # if find container_name of different entity are different but the container entity_type are the same, update the second entity's container entity_type to be original entity_type-2,the third to be original entity_type-3...
        compare1_entities,compare1_result_entities = update_container_types_optimized(compare1_entities,compare1_result_entities)
        #if the last result_container share the same container_name with any entity, update the container_name of result_container.
        if compare1_result_entities and compare1_entities: 
            # [e.update({'container_name': '', 'container_type': ''}) for e in compare1_entities if e.get('container_name') == compare1_result_entities[-1].get('container_name')]
            last_container = compare1_result_entities[-1].get('container_name')
            if any(e.get('container_name') == last_container for e in compare1_entities) and last_container:
                compare1_result_entities[-1]['container_name'] = f"{last_container} (result)"
        

        
        # if find container_name of different entity are different but the container entity_type are the same, update the second entity's container entity_type to be original entity_type-2,the third to be original entity_type-3...
        compare2_entities,compare2_result_entities = update_container_types_optimized(compare2_entities,compare2_result_entities)
        if compare2_result_entities and compare2_entities: 
            # [e.update({'container_name': '', 'container_type': ''}) for e in compare1_entities if e.get('container_name') == compare1_result_entities[-1].get('container_name')]
            last_container = compare2_result_entities[-1].get('container_name')
            if any(e.get('container_name') == last_container for e in compare2_entities) and last_container:
                compare2_result_entities[-1]['container_name'] = f"{last_container} (result)"


        # compare1_operations = compare1_operations[::-1]
        # compare2_operations = compare2_operations[::-1]
        compare1_operations = [{"entity_type": op} for op in compare1_operations]
        compare2_operations = [{"entity_type": op} for op in compare2_operations]
        print(f"compare 1 operations: {compare1_operations}")
        print(f"compare 1 entities: {compare1_entities}")
        print(f"compare 1 result Entities: {compare1_result_entities}")

        print(f"compare 2 operations: {compare2_operations}")
        print(f"compare 2 entities: {compare2_entities}")
        print(f"compare 2 result Entities: {compare2_result_entities}")
        try:
            created, svg_width, svg_height = handle_comparison(compare1_operations, compare1_entities, compare1_result_entities,
                          compare2_operations, compare2_entities, compare2_result_entities,
                          svg_root,resources_path)
        except:
            print("Error in handle_comparison")
            created = False
    else:
        operations, entities, result_entities = extract_operations_and_entities(data)

        # if result_entities and entities: 
        #     [e.update({'container_name': '', 'container_type': ''}) for e in entities if e.get('container_name') == result_entities[-1].get('container_name')]

        # if find container_name of different entity are different but the container entity_type are the same, update the second entity's container entity_type to be original entity_type-2,the third to be original entity_type-3...
        entities,result_entities = update_container_types_optimized(entities,result_entities)
        #if the last result_container share the same container_name with any entity, update the container_name of result_container.
        if result_entities and entities: 
            # [e.update({'container_name': '', 'container_type': ''}) for e in compare1_entities if e.get('container_name') == compare1_result_entities[-1].get('container_name')]
            last_container = result_entities[-1].get('container_name')
            if any(e.get('container_name') == last_container for e in entities) and last_container:
                result_entities[-1]['container_name'] = f"{last_container} (result)"



        # operations = operations[::-1]
        operations = [{"entity_type": op} for op in operations]
        print(f"Operations: {operations}")
        print(f"Entities: {entities}")
        print(f"Result Entities: {result_entities}")

        try:
            created, svg_width, svg_height = handle_all_except_comparison(operations, entities, svg_root, resources_path,result_entities)
        except:
            created = False
       
    # Write to output file
    print(f"SVG created: {created}")
    if created:
        with open(output_file, "wb") as f:
            f.write(etree.tostring(svg_root, pretty_print=True))
        display(SVG(output_file))
    else:
        print("error_message: ",error_message)
    return created




if __name__ == "__main__":
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(current_dir, 'output_visual_formal')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, '01.svg')
    svg_dataset = os.path.join(current_dir, 'svg_dataset')
    visual_language = ["surplus(container1[entity_name: gingerbread cookie, entity_type: gingerbread-cookie, entity_quantity: 10, container_name: home, container_type: home, attr_name: , attr_type: ], container2[entity_name: gingerbread cookie, entity_type: gingerbread-cookie, entity_quantity: 3, container_name: tiny glass jar, container_type: jar, attr_name:, attr_type: ], result_entity[entity_name: gingerbread cookie, entity_type: gingerbread-cookie, entity_quantity: 1, container_name: unplaced cookies, container_type: remainder, attr_name: , attr_type: ])"]
    data = parse_dsl(visual_language[0])
    render_svgs_from_data(output_path, svg_dataset, data)