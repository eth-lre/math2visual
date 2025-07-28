import re
from lxml import etree
import math
import os
from IPython.display import SVG, display
from collections import defaultdict
import random
import copy
import difflib
import inflect
# Global cache for SVG files in each directory
_svg_directory_cache = {}

# Initialize the inflect engine
p = inflect.engine()

error_message = ""
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

    def split_containers(inside_str):
        """Safely splits containers or nested operations while balancing parentheses and square brackets."""
        containers = []
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
                containers.append(buffer.strip())
                buffer = ""
            else:
                buffer += char

        if buffer:
            containers.append(buffer.strip())

        return containers

    def recursive_parse(input_str):
        """Recursively parses operations and containers."""
        input_str = " ".join(input_str.strip().split())  # Clean spaces
        # func_pattern = r"(\w+)\((.*)\)"
        func_pattern = r"(\w+)\s*\((.*)\)"
        match = re.match(func_pattern, input_str)

        if not match:
            raise ValueError(f"DSL does not match the expected pattern: {input_str}")

        operation, inside = match.groups()  # Extract operation and content
        parsed_containers = []
        result_container = None

        # Safely split containers
        for entity in split_containers(inside):
            if any(entity.startswith(op) for op in operations_list):
                # Recognize and recurse into nested operations
                parsed_containers.append(recursive_parse(entity))
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
                    parsed_containers.append(entity_dict)

        result = {"operation": operation, "containers": parsed_containers}
        if result_container:
            result["result_container"] = result_container

        return result

    return recursive_parse(dsl_str)

def remove_svg_blanks(svg_path, output_path):

    # Parse the SVG
    parser = etree.XMLParser(remove_blank_text=True)
    tree = etree.parse(svg_path, parser)
    root = tree.getroot()

    # Namespace handling
    nsmap = {"svg": "http://www.w3.org/2000/svg"}
    if "xmlns" in root.attrib:
        nsmap["svg"] = root.attrib["xmlns"]

    # Calculate bounding box
    min_x, min_y, max_x, max_y = float("inf"), float("inf"), float("-inf"), float("-inf")

    for elem in root.xpath("//*[local-name()='path' or local-name()='rect' or local-name()='circle' or local-name()='line' or local-name()='polygon' or local-name()='ellipse']", namespaces=nsmap):
        bbox = elem.attrib.get("d")  # For paths, you might need a library like `svg.path` for accurate parsing
        tag = etree.QName(elem.tag).localname

        if tag in {"rect", "circle", "ellipse", "line", "polygon"}:
            # Extract specific bounding attributes
            if tag == "rect":
                x = float(elem.attrib.get("x", 0))
                y = float(elem.attrib.get("y", 0))
                w = float(elem.attrib.get("width", 0))
                h = float(elem.attrib.get("height", 0))
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x + w)
                max_y = max(max_y, y + h)
            elif tag == "circle":
                cx = float(elem.attrib.get("cx", 0))
                cy = float(elem.attrib.get("cy", 0))
                r = float(elem.attrib.get("r", 0))
                min_x = min(min_x, cx - r)
                min_y = min(min_y, cy - r)
                max_x = max(max_x, cx + r)
                max_y = max(max_y, cy + r)
            # Handle other shapes like line, ellipse, etc., similarly.

    # Update viewBox and dimensions
    if min_x < float("inf") and min_y < float("inf"):
        new_width = max_x - min_x
        new_height = max_y - min_y
        root.attrib["viewBox"] = f"{min_x} {min_y} {new_width} {new_height}"
        root.attrib["width"] = str(new_width)
        root.attrib["height"] = str(new_height)

    # Write the cleaned SVG back
    tree.write(output_path, pretty_print=True, xml_declaration=True, encoding="utf-8")

    print(f"Cleaned SVG saved to {output_path}")

def render_svgs_from_data(output_file, resources_path, data):
    global error_message
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
    
    
    
    def extract_operations_and_containers(
        node,
        operations=None,
        containers=None,
        result_containers=None,
        parent_op=None,
        parent_container_name=None
    ):
        if operations is None:
            operations = []
        if containers is None:
            containers = []
        if result_containers is None:
            result_containers = []

        op = node.get("operation", "")

        # 1) If operation is "unittrans", just handle special logic and return
        if op == "unittrans":
            sub_ents = node.get("containers", [])
            if len(sub_ents) == 2:
                main_entity = sub_ents[0]
                unit_entity = sub_ents[1]
                # Example: store unit conversion info
                main_entity["unittrans_unit"]  = unit_entity["name"]
                main_entity["unittrans_value"] = unit_entity["item"]["entity_quantity"]
                containers.append(main_entity)
            return operations, containers, result_containers

        # 2) "comparison"? If not handled, raise or skip
        if op == "comparison":
            raise ValueError("We do not handle 'comparison' in this snippet")

        # 3) For normal operations (like addition, subtraction, multiplication, division)
        child_ents = node.get("containers", [])
        my_result  = node.get("result_container")

        if len(child_ents) < 2:
            # Not enough children to form an operation—skip
            return operations, containers, result_containers

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
                # Possibly skip brackets if the parent/child op is associative
                # and container_name is the same, etc. Tweak logic as desired:
                if not can_skip_same_precedence(parent_op, op):
                    # It's a non-associative scenario => must bracket
                    need_brackets = True
  

        # Track how many containers we already had before handling this sub-expression
        start_len = len(containers)

        # --- A) Handle left child ---
        if "operation" in left_child:
            extract_operations_and_containers(
                left_child,
                operations,
                containers,
                result_containers,
                parent_op=op,
                parent_container_name=container_name
            )
        else:
            # Leaf entity
            containers.append(left_child)

        # --- B) Record the current operation ---
        operations.append(op)

        # --- C) Handle right child ---
        if "operation" in right_child:
            extract_operations_and_containers(
                right_child,
                operations,
                containers,
                result_containers,
                parent_op=op,
                parent_container_name=container_name
            )
        else:
            # Leaf entity
            containers.append(right_child)

        # --- D) Mark brackets if needed ---
        if need_brackets:
            # The entire sub-expression is in containers[start_len:]
            if len(containers) > start_len:
                # Mark the first entity with bracket="left"
                containers[start_len]["bracket"] = "left"
                # Mark the last entity in this chunk with bracket="right"
                containers[-1]["bracket"] = "right"

        # --- E) If this is the top-level node (no parent_op), record the result entity ---
        if parent_op is None and my_result:
            if isinstance(my_result, dict):
                result_containers.append(my_result)

        return operations, containers, result_containers



    
    def extract_operations_and_containers_for_comparison(data):
        """
        Extract two sides (compare1 and compare2) from a top-level comparison.
        We assume data["operation"] == "comparison".
        Returns 6 separate lists:
            compare1_operations, compare1_containers, compare1_result_containers,
            compare2_operations, compare2_containers, compare2_result_containers
        """

        # Make sure data["containers"] exists and has 2 items
        if "containers" not in data or len(data["containers"]) < 2:
            # Malformed data => Return empty
            return [], [], [], [], [], []

        # The first item is compare1, the second is compare2
        compare1_data = data["containers"][0]
        compare2_data = data["containers"][1]

        # We'll parse each side with your original function
        # But that function might return 2 items or 3 items depending on 'unittrans'
        def safe_extract(data_piece):
            ret = extract_operations_and_containers(data_piece)
            if len(ret) == 2:
                # Means it was (operations, containers_list) => no result containers returned
                ops, ents = ret
                res = []
            else:
                # Means it was (operations, containers_list, result_containers_list)
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
        
    #     return containers
    def update_container_types_optimized(containers, result_containers):
        """
        Update the container_type for containers in the same group (by container_type)
        when there is more than one unique container_name. In addition, treat the last
        item of result_containers as one of the containers (by reference) so that its
        container_type is updated if necessary.
        
        If there is only one unique container_name for a given container_type,
        leave it unchanged. Otherwise, assign a unique container_type value for each
        container_name within that group.
        
        Parameters:
        containers (list): List of entity dictionaries.
        result_containers (list): List of result entity dictionaries.
            If non-empty, the last item will be processed along with containers.
        
        Returns:
        A tuple (containers, result_containers) where:
            - containers: the original list (with updated container_type values)
            - result_containers: the modified list (the last item updated as needed)
        """
        # Create a temporary combined list from containers.
        combined = containers[:]  # shallow copy; dictionary objects remain the same
        if result_containers:
            # Append the last result entity (by reference) to combined.
            combined.append(result_containers[-1])
        
        # Group combined items by the original container_type.
        entity_type_to_containers = defaultdict(list)
        for entity in combined:
            entity_type_to_containers[entity['container_type']].append(entity)
        
        # Iterate through each container_type group.
        for container_type, group in entity_type_to_containers.items():
            # Group further by container_name.
            name_to_containers = defaultdict(list)
            for entity in group:
                name_to_containers[entity['container_name']].append(entity)
            
            # If there is only one unique container_name in this group, nothing to change.
            if len(name_to_containers) <= 1:
                continue
            
            # Initialize modification index.
            modification_index = 1  # for the first unique container_name, leave container_type unchanged.
            
            # Iterate through unique container_name groups in insertion order.
            for name, ent_group in name_to_containers.items():
                if modification_index == 1:
                    # Use the original container_type for the first group.
                    new_entity_type = container_type
                else:
                    new_entity_type = container_type + "-" + str(modification_index)
                # Set the container_type for all containers in this group.
                for entity in ent_group:
                    entity['container_type'] = new_entity_type
                modification_index += 1

        return containers, result_containers
    
    def handle_multiplication(operations, containers, svg_root, resources_path,result_containers,start_x = 50,start_y = 150):
        global error_message
        print("Handling multiplication")
        # We assume exactly 2 containers, where the second is the multiplier
        if containers[1].get("item", {}).get("entity_quantity", 0) > 12:
            print("No INTUITIVE visual can be generated because of multiplier has entity_quantity higher than 12")
            error_message = "No INTUITIVE visual can be generated because of multiplier has entity_quantity higher than 12"

            return
        if len(containers) == 2 and containers[1]["item"].get("entity_type", "") == "multiplier":
            # How many times to replicate
            multiplier_val = int(containers[1]["item"].get("entity_quantity", 1))

            # Make copies of the first entity
            base_entity = containers[0]
            replicated = []
            for i in range(multiplier_val):
                e_copy = copy.deepcopy(base_entity)
                # Optionally tag each copy for debugging
                e_copy["replica_index"] = i
                replicated.append(e_copy)

            containers = replicated
    
         # Constants
        UNIT_SIZE = 40
        APPLE_SCALE = 0.75
        ITEM_SIZE = int(UNIT_SIZE * APPLE_SCALE)
        ITEM_PADDING = int(UNIT_SIZE * 0.25)
        BOX_PADDING = UNIT_SIZE
        OPERATOR_SIZE = 30
        MAX_ITEM_DISPLAY = 10
        MARGIN = 50
        if any("unittrans_unit" in entity for entity in containers):
            ITEM_SIZE = 3 * ITEM_SIZE


        # Extract quantities and entity_types
        quantities = [e["item"].get("entity_quantity", 0) for e in containers]
        entity_types = [e["item"].get("entity_type", "") for e in containers]

        any_multiplier = any(t == "multiplier" for t in entity_types)
        any_above_20 = any(q > MAX_ITEM_DISPLAY for q in quantities)

        # Determine entity layout entity_type first
        for e in containers:
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "")
            container = e.get("container_type", "")
            attr = e.get("attr_type", "")

            
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

        # Focus on normal layout containers
        normal_container = [e for e in containers if e["layout"] == "normal"]

        # Compute global layout for normal containers:
        # 1. Find the largest entity_quantity among normal layout containers
        if normal_container:
            largest_normal_q = max(e["item"].get("entity_quantity",0) for e in normal_container)
        else:
            largest_normal_q = 1

        # 2. Compute global max_cols and max_rows for this largest normal q
        if largest_normal_q > 0:
            max_cols = int(math.ceil(math.sqrt(largest_normal_q)))
            max_rows = (largest_normal_q + max_cols - 1) // max_cols
        else:
            max_cols, max_rows = 1, 1

        # Assign these global cols and rows to all normal containers
        for e in normal_container:
            e["cols"] = max_cols
            e["rows"] = max_rows

        # For row/column containers and large containers, compute cols/rows individually
        unit_trans_padding = 0
        for e in containers:
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
        # large_total_width = text_width + 10 + UNIT_SIZE + 10 + UNIT_SIZE  #
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

        for e in containers:
            w,h = compute_entity_box_size(e)
            e["planned_width"] = w
            if e.get("unittrans_unit", ""):
                e["planned_height"] = h + 50
            else:
                e["planned_height"] = h

            # print('e["planned_width"]', e["planned_width"])
            # print('e["planned_height"]', e["planned_height"])


        # Position planning 
        # 1) Separate out repeated containers vs. multiplier
        
        repeated_ents = [e for e in containers if e.get("layout") != "multiplier"]
        container_name = containers[0].get('container_name',"")
        print("container_name: ",container_name)
        # 2) Decide how to lay out repeated containers in a grid
        count = len(repeated_ents)
        if container_name == "row":
            grid_cols = 1
            grid_rows = (count + grid_cols - 1) // grid_cols
        elif container_name == "column":
            grid_rows = 1
            grid_cols = (count + grid_rows - 1) // grid_rows
        elif count > 0:
            grid_cols = int(math.ceil(math.sqrt(count)))
            grid_rows = (count + grid_cols - 1) // grid_cols
        else:
            grid_cols = 1
            grid_rows = 1

        # Adjust how much horizontal/vertical gap between entity boxes
        gap_x = 20
        gap_y = 20

        # start_x, start_y = 50, 150
        # start_x, start_y 

        # We'll store the maximum X and Y for final SVG size
        current_max_x = 0
        current_max_y = 0

        # 3) Assign positions to each repeated entity
        #    Add an extra (UNIT_SIZE + 5) vertical offset per row to ensure
        #    any top text does not collide with the entity above.
        for i, e in enumerate(repeated_ents):
            row = i // grid_cols
            col = i % grid_cols

            
            if i == 0:
                # Compute top-left corner
                x_pos = start_x 
                # Notice we add (UNIT_SIZE + 5) extra for each new row:
                y_pos = start_y 
            else:
                x_pos = start_x + col * (repeated_ents[i-1]["planned_width"] + gap_x)
                # Notice we add (UNIT_SIZE + 5) extra for each new row:
                y_pos = start_y + row * (repeated_ents[i-1]["planned_height"] + gap_y + UNIT_SIZE + 5)

            e["planned_x"] = x_pos
            e["planned_y"] = y_pos
            e["planned_box_y"] = y_pos
            

            # Track how far right/down we've gone
            right_edge = x_pos + e["planned_width"]
            bottom_edge = y_pos + e["planned_height"]
            if right_edge > current_max_x:
                current_max_x = right_edge
            if bottom_edge > current_max_y:
                current_max_y = bottom_edge



        max_x, max_y = 0,0
        def update_max_dimensions(x_val, y_val):
            nonlocal max_x, max_y
            if x_val > max_x:
                max_x = x_val
            if y_val > max_y:
                max_y = y_val

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
        def get_figure_svg_path(attr_type):
            global error_message
            if attr_type:
                return os.path.join(resources_path, f"{attr_type}.svg")
            error_message = "Cannot find figure path for attr_type: " + attr_type
            print("Cannot find figure path for attr_type: ", attr_type)
            return None

    
        def embed_top_figures_and_text(parent, box_x, box_y, box_width, container_type, container_name, attr_type, attr_name):
            print("calling embed_top_figures_and_text")
            # print("container_type", container_type)
            # print("container_name", container_name)
            items = []
            show_something = container_name or container_type or attr_name or attr_type
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

                if attr_type and attr_name:
                    figure_path = get_figure_svg_path(attr_type)
                    if figure_path and os.path.exists(figure_path):
                        items.append(("svg", attr_type))
                    items.append(("text", attr_name))

            total_width = 0
            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    total_width += UNIT_SIZE
                else:
                    total_width += 50
                if idx < len(items) - 1:
                    total_width += 10

            group = etree.SubElement(parent, "g")
            start_x_txt = box_x + (box_width - total_width) / 2
            center_y = box_y - UNIT_SIZE - 5
            current_x = start_x_txt

            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    figure_path = get_figure_svg_path(v)
                    if figure_path and os.path.exists(figure_path):
                        svg_el = embed_svg(figure_path, x=current_x, y=center_y, width=UNIT_SIZE, height=UNIT_SIZE)
                        # Append the returned svg element to the group
                        group.append(svg_el)
                    current_x += UNIT_SIZE
                else:
                    text_y = center_y + UNIT_SIZE / 2
                    text_element = etree.SubElement(group, "text", x=str(current_x), y=str(text_y),
                                                    style="font-size: 15px;", dominant_baseline="middle")
                    text_element.text = v
                    current_x += 50
                if idx < len(items) - 1:
                    current_x += 10

        

        def draw_entity(e):
            print('new entity:', e)
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "apple")
            container_name = e.get("container_name", "").strip()
            container_type = e.get("container_type", "").strip()
            attr_name = e.get("attr_name", "").strip()
            attr_type = e.get("attr_type", "").strip()

            # UnitTrans-specific attributes
            unittrans_unit = e.get("unittrans_unit", "")
            unittrans_value = e.get("unittrans_value", "")

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
                text_x = x
                # Adjust text_y to align with operator
                text_y = start_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2) + 30
                text_element = etree.SubElement(svg_root, "text", x=str(text_x), y=str(text_y),
                                                style="font-size: 50px;", dominant_baseline="middle")
                text_element.text = q_str
                update_max_dimensions(text_x + len(q_str)*30, text_y + 50)
                return
            # Draw box
            etree.SubElement(svg_root, "rect", x=str(x), y=str(box_y),
                            width=str(w), height=str(h), stroke="black", fill="none")
            update_max_dimensions(x + w, y + h)

            
            


            # Embed text or figures at the top of each entity box
            
            embed_top_figures_and_text(svg_root, x, box_y, w, container_type, container_name, attr_type, attr_name)


            if layout == "large":

                # Large scenario
                q = float(q)
                if q.is_integer():
                    q_str = str(int(q))  # Convert to integer
                else:
                    q_str = str(q)  # Keep as is
                tw = len(q_str)*20

                total_width = ITEM_SIZE * 4
                start_x_line = x + (w - total_width)/2
                svg_x = start_x_line
                center_y_line = y + (h - UNIT_SIZE)/2
                svg_y = center_y_line - 1.5 * ITEM_SIZE
                svg_y = y + ITEM_PADDING
                text_y = y + ITEM_PADDING + 2.4 * ITEM_SIZE
                text_x = svg_x+ITEM_SIZE*1.

                unit_trans_padding = 50 if unittrans_unit else 0
                svg_y = svg_y + unit_trans_padding
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

                 
                    unittrans_text = f"{unittrans_value}"
             
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
                        
                    # Draw the item
                    for i in range(int(q)):
                        row = i // cols
                        col = i % cols
                        unit_trans_padding = 0
                        if unittrans_unit:
                            unit_trans_padding = 50
                        item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                        if row == 0:
                            item_y = y + BOX_PADDING / 2 + unit_trans_padding
                        else:
                            item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING + unit_trans_padding) + unit_trans_padding

                        # Draw the item
                        svg_root.append(embed_svg(item_svg_path, x=item_x, y=item_y, width=ITEM_SIZE, height=ITEM_SIZE))
                        # Cross colors (use predefined and fallback to random colors if needed)
                        cross_colors = ["black", "red", "blue"]
                        used_colors = set()

                        # Iterate through each subtrahend
                        for idx, sub_entity_quantity in enumerate(e.get("subtrahend_entity_quantity", [])):
                            color = cross_colors[idx] if idx < len(cross_colors) else f"#{''.join([random.choice('0123456789ABCDEF') for _ in range(6)])}"
                            while color in used_colors:  # Ensure no duplicate random colors
                                color = f"#{''.join([random.choice('0123456789ABCDEF') for _ in range(6)])}"
                            used_colors.add(color)

                            # Determine the number of items to cross for this subtrahend
                            start_cross_idx = int(q) - sum(e["subtrahend_entity_quantity"][:idx + 1])  # Start index for current subtrahend
                            end_cross_idx = int(q) - sum(e["subtrahend_entity_quantity"][:idx])       # End index for current subtrahend

                            # Apply crosses for the current subtrahend
                            for i in range(start_cross_idx, end_cross_idx):
                                row = i // cols
                                col = i % cols
                                item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                                item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING)

                                # Draw horizontal line of the cross
                                line1 = etree.Element(
                                    "line",
                                    x1=str(item_x),
                                    y1=str(item_y),
                                    x2=str(item_x + ITEM_SIZE),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line1)

                                # Draw vertical line of the cross
                                line2 = etree.Element(
                                    "line",
                                    x1=str(item_x + ITEM_SIZE),
                                    y1=str(item_y),
                                    x2=str(item_x),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line2)

                        if unittrans_unit:
                            # Define circle position
                            circle_radius = 30
                            # circle_center_x = item_x + ITEM_SIZE -5 
                            circle_center_x = item_x + ITEM_SIZE/2
                            circle_center_y = item_y - circle_radius # Above the top-right corner of the item

                            # Add purple circle
                            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                                            r=str(circle_radius), fill="#BBA7F4")


                            unittrans_text = f"{unittrans_value}"

                            text_element = etree.SubElement(svg_root, "text",
                                                            x=str(circle_center_x-15), #
                                                            y=str(circle_center_y + 5),  # Center text vertically
                                                            style="font-size: 15px;",
                                                            text_anchor="middle",  # Center align text
                                                            dominant_baseline="middle")  # Center align text vertically
                            text_element.text = unittrans_text


            


        # Draw containers
        for entity in containers:  # Assuming exactly two containers
            print("entity: ", entity)
            draw_entity(entity)
        
        # Draw operator
        
        operator_svg_mapping = {
            "surplus": "division",  # Map 'surplus' to 'subtraction.svg'
            "default": "addition"      # Fallback default operator
        }
    

        # Update SVG size
        final_width = max_x + MARGIN
        final_height = max_y + MARGIN + 50
        svg_root.attrib["width"] = str(final_width)
        svg_root.attrib["height"] = str(final_height)

        # Draw big box
        if len(containers) > 1:
            big_box_x = 20 # Add padding on the left
            big_box_y = 80  # Start above the figures and text
            big_box_width = max_x + 2* MARGIN - 80# Add padding on the right
            big_box_height = max_y + 2* MARGIN - 90 # Extend below the smaller boxes
            
            # Embed text and figures at the top of the big box
            result_container = result_containers[-1]
            embed_top_figures_and_text(svg_root, big_box_x, big_box_y, big_box_width, result_container['container_type'], result_container['container_name'], result_container['attr_type'], result_container['attr_name'])

            etree.SubElement(svg_root, "rect", x=str(big_box_x), y=str(big_box_y), width=str(big_box_width),
                            height=str(big_box_height), stroke="black", fill="none", stroke_width="2")
            
            # Update SVG size
            final_width = max_x + 2* MARGIN
            final_height = max_y + 2*  MARGIN + 50
            svg_root.attrib["width"] = str(final_width)
            svg_root.attrib["height"] = str(final_height)

            # Add a purple circle at the bottom-right corner of the big box
            circle_radius = 30
            circle_center_x = big_box_x + big_box_width
            circle_center_y = big_box_y + big_box_height
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?"
            # Save the combined SVG
            # Adjust SVG canvas size dynamically (including the circle)
            svg_padding = 20  # Optional padding for the edges
            circle_extra_space = circle_radius * 2  # Ensure the circle is fully included
        else:
            e = containers[0]
            # print('e.get("subtrahend_entity_quantity", 0) > 20',e.get("subtrahend_entity_quantity", 0) )
            

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            # Add a purple circle at the bottom-right corner of the big box
            circle_radius = 30
            circle_center_x = x + w
            circle_center_y = y + h
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?"
        
        return True, str(float(svg_root.attrib["width"]) - start_x), str(float(svg_root.attrib["height"]) - MARGIN + 15)
        
    def is_int(value):
        try:
            # Convert to float first, then check if it can be cast to an integer
            float_value = float(value)
            return float_value.is_integer()
        except ValueError:
            # If conversion fails, it's not a valid number
            return False
    def handle_division(operations, containers, svg_root, resources_path,result_containers,start_x = 50 ,start_y = 150):
        global error_message
        # Ensure exactly two containers: the dividend and divisor
        print("Handling division")
        if len(containers) != 2:
            print("Division requires exactly two containers.")
            error_message = "Division requires exactly two containers."
            return
        original_containers = containers
        # Extract dividend and divisor
        dividend_entity = containers[0]
        divisor_entity = containers[1]
        
        if not is_int(dividend_entity["item"].get("entity_quantity", 0)) or not is_int(divisor_entity["item"].get("entity_quantity", 1)):
            print("One or both of the containers are not integers.")
            error_message = "One or both of the containers are not integers."
            return
        else:
            dividend_entity_quantity = int(dividend_entity["item"].get("entity_quantity", 0))
            divisor_entity_quantity = int(divisor_entity["item"].get("entity_quantity", 1))


        if divisor_entity_quantity <= 0:
            print("Cannot divide by zero or negative entity_quantity.")
            error_message = "Cannot divide by zero or negative entity_quantity."
            return
        
        # Calculate the number of results
        if dividend_entity_quantity % divisor_entity_quantity == 0:
            result_count = dividend_entity_quantity // divisor_entity_quantity
        else:
            print(f"INTUITIVE visual not possible: {dividend_entity_quantity} cannot be evenly divided by {divisor_entity_quantity}")
            error_message = f"INTUITIVE visual not possible: {dividend_entity_quantity} cannot be evenly divided by {divisor_entity_quantity}"
            return None
        
        flag_division_entity_type_same = True
        if(dividend_entity["item"].get("entity_type", "") == divisor_entity["item"].get("entity_type", "") and dividend_entity["item"].get("entity_type", "") and divisor_entity["item"].get("entity_type", "")):
   
            flag_division_entity_type_same = True
            print("entity_type equal")
            if(result_count > 12):
                error_message = "Division result rectangle number higher than 12."
                return
            # Create replicated containers based on the result count
            visual_entity = copy.deepcopy(dividend_entity)
            visual_entity["item"]["entity_quantity"] = divisor_entity_quantity
            if divisor_entity['container_name']:
                visual_entity['container_name'] = divisor_entity['container_name']
                visual_entity['container_type'] = divisor_entity['container_type']
            else:
                visual_entity['container_name'] = divisor_entity['entity_name']
                visual_entity['container_type'] = divisor_entity['item']['entity_type']
            visual_entity['attr_name'] = divisor_entity['attr_name']
            visual_entity['attr_type'] = divisor_entity['attr_type']
            replicated = []
            for i in range(result_count):
                e_copy = copy.deepcopy(visual_entity)
                e_copy["replica_index"] = i
                replicated.append(e_copy)

            containers = replicated
        elif(dividend_entity["item"].get("entity_type", "") != divisor_entity["item"].get("entity_type", "") and dividend_entity["item"].get("entity_type", "") and divisor_entity["item"].get("entity_type", "")):
            
            flag_division_entity_type_same = False
            print("entity_type different")
            if(divisor_entity_quantity > 12):
                error_message = "Division result rectangle number higher than 12."
                return
            # Create replicated containers based on the result count
            visual_entity = copy.deepcopy(dividend_entity)
            visual_entity["item"]["entity_quantity"] = result_count
            if divisor_entity['entity_name']:
                visual_entity['container_name'] = divisor_entity['entity_name']
                visual_entity['container_type'] = divisor_entity['item']['entity_type']
            else:
                visual_entity['container_name'] = divisor_entity['container_name']
                visual_entity['container_type'] = divisor_entity['container_type']
            visual_entity['attr_name'] = divisor_entity['attr_name']
            visual_entity['attr_type'] = divisor_entity['attr_type']
            replicated = []
            for i in range(divisor_entity_quantity):
                e_copy = copy.deepcopy(visual_entity)
                e_copy["replica_index"] = i
                replicated.append(e_copy)

            containers = replicated
        else:
            print("Division requires entity_type of containers.")
            error_message = "Division requires entity_type of containers."
            return

        # Constants
        UNIT_SIZE = 40
        APPLE_SCALE = 0.75
        ITEM_SIZE = int(UNIT_SIZE * APPLE_SCALE)
        ITEM_PADDING = int(UNIT_SIZE * 0.25)
        BOX_PADDING = UNIT_SIZE
        OPERATOR_SIZE = 30
        MAX_ITEM_DISPLAY = 10
        MARGIN = 50
        if any("unittrans_unit" in entity for entity in containers):
            ITEM_SIZE = 3 * ITEM_SIZE


        # Extract quantities and entity_types
        quantities = [e["item"].get("entity_quantity", 0) for e in containers]
        entity_types = [e["item"].get("entity_type", "") for e in containers]

        any_multiplier = any(t == "multiplier" for t in entity_types)
        any_above_20 = any(q > MAX_ITEM_DISPLAY for q in quantities)

        # Determine entity layout entity_type first
        for e in containers:
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "")
            container = e.get("container_type", "")
            attr = e.get("attr_type", "")

            
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

        # Focus on normal layout containers
        normal_container = [e for e in containers if e["layout"] == "normal"]

        # Compute global layout for normal containers:
        # 1. Find the largest entity_quantity among normal layout containers
        if normal_container:
            largest_normal_q = max(e["item"].get("entity_quantity",0) for e in normal_container)
        else:
            largest_normal_q = 1

        # 2. Compute global max_cols and max_rows for this largest normal q
        if largest_normal_q > 0:
            max_cols = int(math.ceil(math.sqrt(largest_normal_q)))
            max_rows = (largest_normal_q + max_cols - 1) // max_cols
        else:
            max_cols, max_rows = 1, 1

        # Assign these global cols and rows to all normal containers
        for e in normal_container:
            e["cols"] = max_cols
            e["rows"] = max_rows

        # For row/column containers and large containers, compute cols/rows individually
        unit_trans_padding = 0
        for e in containers:
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
        # large_total_width = text_width + 10 + UNIT_SIZE + 10 + UNIT_SIZE  #
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

        for e in containers:
            w,h = compute_entity_box_size(e)
            e["planned_width"] = w
            if e.get("unittrans_unit", ""):
                e["planned_height"] = h + 50
            else:
                e["planned_height"] = h



        # Position planning 
        # 1) Separate out repeated containers vs. multiplier
        
        repeated_ents = [e for e in containers if e.get("layout") != "multiplier"]

        # 2) Decide how to lay out repeated containers in a grid
        count = len(repeated_ents)
        if count > 0:
            grid_cols = int(math.ceil(math.sqrt(count)))
            grid_rows = (count + grid_cols - 1) // grid_cols
        else:
            grid_cols = 1
            grid_rows = 1

        # Adjust how much horizontal/vertical gap between entity boxes
        gap_x = 20
        gap_y = 20

        # start_x, start_y = 50, 150

        # We'll store the maximum X and Y for final SVG size
        current_max_x = 0
        current_max_y = 0

        # 3) Assign positions to each repeated entity
        #    Add an extra (UNIT_SIZE + 5) vertical offset per row to ensure
        #    any top text does not collide with the entity above.
        for i, e in enumerate(repeated_ents):
            row = i // grid_cols
            col = i % grid_cols

            if i == 0:
                # Compute top-left corner
                x_pos = start_x 
                # Notice we add (UNIT_SIZE + 5) extra for each new row:
                y_pos = start_y 
            else:
                x_pos = start_x + col * (repeated_ents[i-1]["planned_width"] + gap_x)
                # Notice we add (UNIT_SIZE + 5) extra for each new row:
                y_pos = start_y + row * (repeated_ents[i-1]["planned_height"] + gap_y + UNIT_SIZE + 5)

            e["planned_x"] = x_pos
            e["planned_y"] = y_pos
            e["planned_box_y"] = y_pos
            

            # Track how far right/down we've gone
            right_edge = x_pos + e["planned_width"]
            bottom_edge = y_pos + e["planned_height"]
            if right_edge > current_max_x:
                current_max_x = right_edge
            if bottom_edge > current_max_y:
                current_max_y = bottom_edge



        max_x, max_y = 0,0
        def update_max_dimensions(x_val, y_val):
            nonlocal max_x, max_y
            if x_val > max_x:
                max_x = x_val
            if y_val > max_y:
                max_y = y_val

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
        def get_figure_svg_path(attr_type):
            if attr_type:
                return os.path.join(resources_path, f"{attr_type}.svg")
            return None

    
        def embed_top_figures_and_text(parent, box_x, box_y, box_width, container_type, container_name, attr_type, attr_name):
            print("calling embed_top_figures_and_text")

            items = []
            show_something = container_name or container_type or attr_name or attr_type
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

                if attr_type and attr_name:
                    figure_path = get_figure_svg_path(attr_type)
                    if figure_path and os.path.exists(figure_path):
                        items.append(("svg", attr_type))
                    items.append(("text", attr_name))

            total_width = 0
            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    total_width += UNIT_SIZE
                else:
                    total_width += 50
                if idx < len(items) - 1:
                    total_width += 10

            group = etree.SubElement(parent, "g")
            start_x_txt = box_x + (box_width - total_width) / 2
            center_y = box_y - UNIT_SIZE - 5
            current_x = start_x_txt

            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    figure_path = get_figure_svg_path(v)
                    if figure_path and os.path.exists(figure_path):
                        svg_el = embed_svg(figure_path, x=current_x, y=center_y, width=UNIT_SIZE, height=UNIT_SIZE)
                        # Append the returned svg element to the group
                        group.append(svg_el)
                    current_x += UNIT_SIZE
                else:
                    text_y = center_y + UNIT_SIZE / 2
                    text_element = etree.SubElement(group, "text", x=str(current_x), y=str(text_y),
                                                    style="font-size: 15px;", dominant_baseline="middle")
                    text_element.text = v
                    current_x += 50
                if idx < len(items) - 1:
                    current_x += 10

        

        def draw_entity(e):
            print('new entity:', e)
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "apple")
            container_name = e.get("container_name", "").strip()
            container_type = e.get("container_type", "").strip()
            attr_name = e.get("attr_name", "").strip()
            attr_type = e.get("attr_type", "").strip()

            # UnitTrans-specific attributes
            unittrans_unit = e.get("unittrans_unit", "")
            unittrans_value = e.get("unittrans_value", "")

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            layout = e["layout"]
            cols = e["cols"]
            rows = e["rows"]

            # Adjust box size if unittrans_unit exists
            q = float(q)
            if layout == "multiplier":
                if q.is_integer():
                    q_str = str(int(q))  # Convert to integer
                else:
                    q_str = str(q)  # Keep as is
                text_x = x
                # Adjust text_y to align with operator
                text_y = start_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2) + 30
                text_element = etree.SubElement(svg_root, "text", x=str(text_x), y=str(text_y),
                                                style="font-size: 50px;", dominant_baseline="middle")
                text_element.text = q_str
                update_max_dimensions(text_x + len(q_str)*30, text_y + 50)
                return
            # Draw box
            etree.SubElement(svg_root, "rect", x=str(x), y=str(box_y),
                            width=str(w), height=str(h), stroke="black", fill="none")
            update_max_dimensions(x + w, y + h)

            
            


            # Embed text or figures at the top of each entity box
            
            embed_top_figures_and_text(svg_root, x, box_y, w, container_type, container_name, attr_type, attr_name)


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

             
                # extra vertical space if there's a unittrans
                unit_trans_padding = 50 if unittrans_unit else 0
                svg_y = svg_y + unit_trans_padding
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
                        
                    # Draw the item
                    for i in range(int(q)):
                        row = i // cols
                        col = i % cols
                        unit_trans_padding = 0
                        if unittrans_unit:
                            unit_trans_padding = 50
                        item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                        if row == 0:
                            item_y = y + BOX_PADDING / 2 + unit_trans_padding
                        else:
                            item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING + unit_trans_padding) + unit_trans_padding

                        # Draw the item
                        svg_root.append(embed_svg(item_svg_path, x=item_x, y=item_y, width=ITEM_SIZE, height=ITEM_SIZE))
                        # Cross colors (use predefined and fallback to random colors if needed)
                        cross_colors = ["black", "red", "blue"]
                        used_colors = set()

                        # Iterate through each subtrahend
                        for idx, sub_entity_quantity in enumerate(e.get("subtrahend_entity_quantity", [])):
                            color = cross_colors[idx] if idx < len(cross_colors) else f"#{''.join([random.choice('0123456789ABCDEF') for _ in range(6)])}"
                            while color in used_colors:  # Ensure no duplicate random colors
                                color = f"#{''.join([random.choice('0123456789ABCDEF') for _ in range(6)])}"
                            used_colors.add(color)

                            # Determine the number of items to cross for this subtrahend
                            start_cross_idx = int(q) - sum(e["subtrahend_entity_quantity"][:idx + 1])  # Start index for current subtrahend
                            end_cross_idx = int(q) - sum(e["subtrahend_entity_quantity"][:idx])       # End index for current subtrahend

                            # Apply crosses for the current subtrahend
                            for i in range(start_cross_idx, end_cross_idx):
                                row = i // cols
                                col = i % cols
                                item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                                item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING)

                                # Draw horizontal line of the cross
                                line1 = etree.Element(
                                    "line",
                                    x1=str(item_x),
                                    y1=str(item_y),
                                    x2=str(item_x + ITEM_SIZE),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line1)

                                # Draw vertical line of the cross
                                line2 = etree.Element(
                                    "line",
                                    x1=str(item_x + ITEM_SIZE),
                                    y1=str(item_y),
                                    x2=str(item_x),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line2)

                        if unittrans_unit:
                            # Define circle position
                            circle_radius = 30
                            # circle_center_x = item_x + ITEM_SIZE -5 
                            circle_center_x = item_x + ITEM_SIZE/2
                            circle_center_y = item_y - circle_radius # Above the top-right corner of the item

                            # Add purple circle
                            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                                            r=str(circle_radius), fill="#BBA7F4")


                            unittrans_text = f"{unittrans_value}"

                            text_element = etree.SubElement(svg_root, "text",
                                                            x=str(circle_center_x-15), #
                                                            y=str(circle_center_y + 5),  # Center text vertically
                                                            style="font-size: 15px;",
                                                            text_anchor="middle",  # Center align text
                                                            dominant_baseline="middle")  # Center align text vertically
                            text_element.text = unittrans_text


            


        # Draw containers
        for entity in containers:  # Assuming exactly two containers
            print("entity: ", entity)
            draw_entity(entity)
        
        # Draw operator
      
        operator_svg_mapping = {
            "surplus": "division",  # Map 'surplus' to 'subtraction.svg'
            "default": "addition"      # Fallback default operator
        }



        # Update SVG size
        final_width = max_x + MARGIN
        final_height = max_y + MARGIN + 50
        svg_root.attrib["width"] = str(final_width)
        svg_root.attrib["height"] = str(final_height)

        print("flag_division_entity_type_same", flag_division_entity_type_same)
        # Draw big box
        if len(containers) > 1 and flag_division_entity_type_same:
            big_box_x = 20 # Add padding on the left
            big_box_y = 80  # Start above the figures and text
            big_box_width = max_x + 2* MARGIN - 80# Add padding on the right
            big_box_height = max_y + 2* MARGIN - 90 # Extend below the smaller boxes
            
            # Embed text and figures at the top of the big box
            # result_container = result_containers[-1]
            container_entity = original_containers[0]
            print('container_entity', container_entity)
            embed_top_figures_and_text(svg_root, big_box_x, big_box_y, big_box_width, container_entity['container_type'], container_entity['container_name'], container_entity['attr_type'], container_entity['attr_name'])

            etree.SubElement(svg_root, "rect", x=str(big_box_x), y=str(big_box_y), width=str(big_box_width),
                            height=str(big_box_height), stroke="black", fill="none", stroke_width="2")
            
            # Update SVG size
            final_width = max_x + 2* MARGIN
            final_height = max_y + 2*  MARGIN + 50
            svg_root.attrib["width"] = str(final_width)
            svg_root.attrib["height"] = str(final_height)

            # Add a purple circle at the top-right corner of the big box---division is different!!
            circle_radius = 30
            circle_center_x = big_box_x + big_box_width
            circle_center_y = big_box_y 
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?" 
            # + result_containers[-1]['entity_name']
            # Save the combined SVG
            # Adjust SVG canvas size dynamically (including the circle)
            svg_padding = 20  # Optional padding for the edges
            circle_extra_space = circle_radius * 2  # Ensure the circle is fully included
        elif len(containers) > 1 and not flag_division_entity_type_same:
            big_box_x = 20 # Add padding on the left
            big_box_y = 80  # Start above the figures and text
            big_box_width = max_x + 2* MARGIN - 80# Add padding on the right
            big_box_height = max_y + 2* MARGIN - 90 # Extend below the smaller boxes
            
            # Embed text and figures at the top of the big box
            # result_container = result_containers[-1]
            container_entity = original_containers[0]
            print('container_entity', container_entity)
            embed_top_figures_and_text(svg_root, big_box_x, big_box_y, big_box_width, container_entity['container_type'], container_entity['container_name'], container_entity['attr_type'], container_entity['attr_name'])

            etree.SubElement(svg_root, "rect", x=str(big_box_x), y=str(big_box_y), width=str(big_box_width),
                            height=str(big_box_height), stroke="black", fill="none", stroke_width="2")
            
            # Update SVG size
            final_width = max_x + 2* MARGIN
            final_height = max_y + 2*  MARGIN + 50
            svg_root.attrib["width"] = str(final_width)
            svg_root.attrib["height"] = str(final_height)

            e = containers[-1]

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            # Add a purple circle at the top-right corner of the big box--for division is different!!
            circle_radius = 30
            circle_center_x = x + w
            circle_center_y = y + h
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?" 
        else:
            e = containers[-1]

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            # Add a purple circle at the top-right corner of the big box--for division is different!!
            circle_radius = 30
            circle_center_x = x + w
            circle_center_y = y + h
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?" 



        return True, str(float(svg_root.attrib["width"]) - start_x), str(float(svg_root.attrib["height"]) - MARGIN + 15)
        
    def handle_surplus(operations, containers, svg_root, resources_path,result_containers,start_x = 50 ,start_y = 150):
        global error_message
        print("Handling surplus")
        if len(containers) != 2:
            error_message = "Division requires exactly two containers, but it contains more."
            print("Division requires exactly two containers.")
            return
        original_containers = containers
        # Extract dividend and divisor
        dividend_entity = containers[0]
        divisor_entity = containers[1]

        dividend_entity_quantity = int(dividend_entity["item"].get("entity_quantity", 0))
        divisor_entity_quantity = int(divisor_entity["item"].get("entity_quantity", 1))

        if divisor_entity_quantity <= 0:
            error_message = "Cannot divide by zero or negative entity_quantity."
            print("Cannot divide by zero or negative entity_quantity.")
            return

        # Calculate the number of results
        result_count = dividend_entity_quantity // divisor_entity_quantity

        flag_division_entity_type_same = True
        if(dividend_entity["item"].get("entity_type", "") == divisor_entity["item"].get("entity_type", "") and dividend_entity["item"].get("entity_type", "") and divisor_entity["item"].get("entity_type", "")):
            flag_division_entity_type_same = True
            print("entity_type equal")
            # Create replicated containers based on the result count
            visual_entity = copy.deepcopy(dividend_entity)
            visual_entity["item"]["entity_quantity"] = divisor_entity_quantity

            if divisor_entity['container_name']:
                visual_entity['container_name'] = divisor_entity['container_name']
                visual_entity['container_type'] = divisor_entity['container_type']
            else:
                visual_entity['container_name'] = divisor_entity['entity_name']
                visual_entity['container_type'] = divisor_entity['item']['entity_type']
            visual_entity['attr_name'] = divisor_entity['attr_name']
            visual_entity['attr_type'] = divisor_entity['attr_type']
            replicated = []
            for i in range(result_count):
                e_copy = copy.deepcopy(visual_entity)
                e_copy["replica_index"] = i
                replicated.append(e_copy)

        elif(dividend_entity["item"].get("entity_type", "") != divisor_entity["item"].get("entity_type", "") and dividend_entity["item"].get("entity_type", "") and divisor_entity["item"].get("entity_type", "")):
            flag_division_entity_type_same = False
            print("entity_type different")
            # Create replicated containers based on the result count
            visual_entity = copy.deepcopy(dividend_entity)
            visual_entity["item"]["entity_quantity"] = result_count
            if divisor_entity['entity_name']:
                visual_entity['container_name'] = divisor_entity['entity_name']
                visual_entity['container_type'] = divisor_entity['item']['entity_type']
            else:
                visual_entity['container_name'] = divisor_entity['container_name']
                visual_entity['container_type'] = divisor_entity['container_type']
            visual_entity['attr_name'] = divisor_entity['attr_name']
            visual_entity['attr_type'] = divisor_entity['attr_type']
            replicated = []
            for i in range(divisor_entity_quantity):
                e_copy = copy.deepcopy(visual_entity)
                e_copy["replica_index"] = i
                replicated.append(e_copy)

            containers = replicated
        else:
            print("Surplus requires entity_type of containers.")
            error_message = "Surplus requires entity_type of containers."
            return




        # result_count = dividend_entity_quantity // divisor_entity_quantity
        

        remainder_entity_quantity = dividend_entity_quantity % divisor_entity_quantity
        remainder_entity = copy.deepcopy(visual_entity)
        remainder_entity["item"]["entity_quantity"] = remainder_entity_quantity
        remainder_entity["container_name"] = "Remainder"
        if containers[0]['container_type'] == 'row':
            remainder_entity["container_type"] = "row"  
        else:
            remainder_entity["container_type"] = "remainder"
        remainder_entity["attr_name"] = ""
        remainder_entity["attr_type"] = ""
        replicated.append(remainder_entity)
        containers = replicated





        # Constants
        UNIT_SIZE = 40
        APPLE_SCALE = 0.75
        ITEM_SIZE = int(UNIT_SIZE * APPLE_SCALE)
        ITEM_PADDING = int(UNIT_SIZE * 0.25)
        BOX_PADDING = UNIT_SIZE
        OPERATOR_SIZE = 30
        MAX_ITEM_DISPLAY = 10
        MARGIN = 50
        if any("unittrans_unit" in entity for entity in containers):
            ITEM_SIZE = 3 * ITEM_SIZE


        # Extract quantities and entity_types
        quantities = [e["item"].get("entity_quantity", 0) for e in containers]
        entity_types = [e["item"].get("entity_type", "") for e in containers]

        any_multiplier = any(t == "multiplier" for t in entity_types)
        any_above_20 = any(q > MAX_ITEM_DISPLAY for q in quantities)

        # Determine entity layout entity_type first
        for e in containers:
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "")
            container = e.get("container_type", "")
            attr = e.get("attr_type", "")

            
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

        # Focus on normal layout containers
        normal_container = [e for e in containers if e["layout"] == "normal"]

        # Compute global layout for normal containers:
        # 1. Find the largest entity_quantity among normal layout containers
        if normal_container:
            largest_normal_q = max(e["item"].get("entity_quantity",0) for e in normal_container)
        else:
            largest_normal_q = 1

        # 2. Compute global max_cols and max_rows for this largest normal q
        if largest_normal_q > 0:
            max_cols = int(math.ceil(math.sqrt(largest_normal_q)))
            max_rows = (largest_normal_q + max_cols - 1) // max_cols
        else:
            max_cols, max_rows = 1, 1

        # Assign these global cols and rows to all normal containers
        for e in normal_container:
            e["cols"] = max_cols
            e["rows"] = max_rows

        # For row/column containers and large containers, compute cols/rows individually
        unit_trans_padding = 0
        for e in containers:
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
        # large_total_width = text_width + 10 + UNIT_SIZE + 10 + UNIT_SIZE  #
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

        for e in containers:
            w,h = compute_entity_box_size(e)
            e["planned_width"] = w
            if e.get("unittrans_unit", ""):
                e["planned_height"] = h + 50
            else:
                e["planned_height"] = h

            # print('e["planned_width"]', e["planned_width"])
            # print('e["planned_height"]', e["planned_height"])


        # Position planning 
        # 1) Separate out repeated containers vs. multiplier
        
        repeated_ents = [e for e in containers if e.get("layout") != "multiplier"]

        # 2) Decide how to lay out repeated containers in a grid
        count = len(repeated_ents)
        if count > 0:
            grid_cols = int(math.ceil(math.sqrt(count)))
            grid_rows = (count + grid_cols - 1) // grid_cols
        else:
            grid_cols = 1
            grid_rows = 1

        # Adjust how much horizontal/vertical gap between entity boxes
        gap_x = 20
        gap_y = 20

        # start_x, start_y = 50, 150

        # We'll store the maximum X and Y for final SVG size
        current_max_x = 0
        current_max_y = 0

        # 3) Assign positions to each repeated entity
        #    Add an extra (UNIT_SIZE + 5) vertical offset per row to ensure
        #    any top text does not collide with the entity above.
        for i, e in enumerate(repeated_ents):
            row = i // grid_cols
            col = i % grid_cols

            if i == 0:
                # Compute top-left corner
                x_pos = start_x 
                # Notice we add (UNIT_SIZE + 5) extra for each new row:
                y_pos = start_y 
            else:
                x_pos = start_x + col * (repeated_ents[i-1]["planned_width"] + gap_x)
                # Notice we add (UNIT_SIZE + 5) extra for each new row:
                y_pos = start_y + row * (repeated_ents[i-1]["planned_height"] + gap_y + UNIT_SIZE + 5)

            e["planned_x"] = x_pos
            e["planned_y"] = y_pos
            e["planned_box_y"] = y_pos
            

            # Track how far right/down we've gone
            right_edge = x_pos + e["planned_width"]
            bottom_edge = y_pos + e["planned_height"]
            if right_edge > current_max_x:
                current_max_x = right_edge
            if bottom_edge > current_max_y:
                current_max_y = bottom_edge



        max_x, max_y = 0,0
        def update_max_dimensions(x_val, y_val):
            nonlocal max_x, max_y
            if x_val > max_x:
                max_x = x_val
            if y_val > max_y:
                max_y = y_val

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

        def get_figure_svg_path(attr_type):
            if attr_type:
                return os.path.join(resources_path, f"{attr_type}.svg")
            return None

    
        def embed_top_figures_and_text(parent, box_x, box_y, box_width, container_type, container_name, attr_type, attr_name):
            print("calling embed_top_figures_and_text")
            # print("container_type", container_type)
            # print("container_name", container_name)
            items = []
            show_something = container_name or container_type or attr_name or attr_type
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

                if attr_type and attr_name:
                    figure_path = get_figure_svg_path(attr_type)
                    if figure_path and os.path.exists(figure_path):
                        items.append(("svg", attr_type))
                    items.append(("text", attr_name))

            total_width = 0
            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    total_width += UNIT_SIZE
                else:
                    total_width += 50
                if idx < len(items) - 1:
                    total_width += 10

            group = etree.SubElement(parent, "g")
            start_x_txt = box_x + (box_width - total_width) / 2
            center_y = box_y - UNIT_SIZE - 5
            current_x = start_x_txt

            for idx, (t, v) in enumerate(items):
                if t == "svg":
                    figure_path = get_figure_svg_path(v)
                    if figure_path and os.path.exists(figure_path):
                        svg_el = embed_svg(figure_path, x=current_x, y=center_y, width=UNIT_SIZE, height=UNIT_SIZE)
                        # Append the returned svg element to the group
                        group.append(svg_el)
                    current_x += UNIT_SIZE
                else:
                    text_y = center_y + UNIT_SIZE / 2
                    text_element = etree.SubElement(group, "text", x=str(current_x), y=str(text_y),
                                                    style="font-size: 15px;", dominant_baseline="middle")
                    text_element.text = v
                    current_x += 50
                if idx < len(items) - 1:
                    current_x += 10

        

        def draw_entity(e):
            print('new entity:', e)
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "apple")
            container_name = e.get("container_name", "").strip()
            container_type = e.get("container_type", "").strip()
            attr_name = e.get("attr_name", "").strip()
            attr_type = e.get("attr_type", "").strip()

            # UnitTrans-specific attributes
            unittrans_unit = e.get("unittrans_unit", "")
            unittrans_value = e.get("unittrans_value", "")

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            layout = e["layout"]
            cols = e["cols"]
            rows = e["rows"]

            # Adjust box size if unittrans_unit exists
            # if unittrans_unit:
            #     # w += 50  # Increase width to accommodate the circle
            #     h += 50  # Increase height if needed
            q = float(q)
            if layout == "multiplier":
                if q.is_integer():
                    q_str = str(int(q))  # Convert to integer
                else:
                    q_str = str(q)  # Keep as is
                text_x = x
                # Adjust text_y to align with operator
                text_y = start_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2) + 30
                text_element = etree.SubElement(svg_root, "text", x=str(text_x), y=str(text_y),
                                                style="font-size: 50px;", dominant_baseline="middle")
                text_element.text = q_str
                update_max_dimensions(text_x + len(q_str)*30, text_y + 50)
                return
            # Draw box
            etree.SubElement(svg_root, "rect", x=str(x), y=str(box_y),
                            width=str(w), height=str(h), stroke="black", fill="none")
            update_max_dimensions(x + w, y + h)

            
            


            # Embed text or figures at the top of each entity box
            
            embed_top_figures_and_text(svg_root, x, box_y, w, container_type, container_name, attr_type, attr_name)


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

                # Add multiplication operator SVG
                # current_x = start_x_line + tw + 10
                # multiplication_svg_path = os.path.join(resources_path, "multiplication.svg")
                # svg_root.append(embed_svg(multiplication_svg_path, x=current_x, y=center_y_line, width=OPERATOR_SIZE, height=OPERATOR_SIZE))
                # current_x += OPERATOR_SIZE + 10

                # extra vertical space if there's a unittrans
                unit_trans_padding = 50 if unittrans_unit else 0
                svg_y = svg_y + unit_trans_padding

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
                    
                    unittrans_text = f"{unittrans_value}"

                   
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
                        
                    # Draw the item
                    for i in range(int(q)):
                        row = i // cols
                        col = i % cols
                        unit_trans_padding = 0
                        if unittrans_unit:
                            unit_trans_padding = 50
                        item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                        if row == 0:
                            item_y = y + BOX_PADDING / 2 + unit_trans_padding
                        else:
                            item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING + unit_trans_padding) + unit_trans_padding

                        # Draw the item
                        svg_root.append(embed_svg(item_svg_path, x=item_x, y=item_y, width=ITEM_SIZE, height=ITEM_SIZE))
                        # Cross colors (use predefined and fallback to random colors if needed)
                        cross_colors = ["black", "red", "blue"]
                        used_colors = set()

                        # Iterate through each subtrahend
                        for idx, sub_entity_quantity in enumerate(e.get("subtrahend_entity_quantity", [])):
                            color = cross_colors[idx] if idx < len(cross_colors) else f"#{''.join([random.choice('0123456789ABCDEF') for _ in range(6)])}"
                            while color in used_colors:  # Ensure no duplicate random colors
                                color = f"#{''.join([random.choice('0123456789ABCDEF') for _ in range(6)])}"
                            used_colors.add(color)

                            # Determine the number of items to cross for this subtrahend
                            start_cross_idx = int(q) - sum(e["subtrahend_entity_quantity"][:idx + 1])  # Start index for current subtrahend
                            end_cross_idx = int(q) - sum(e["subtrahend_entity_quantity"][:idx])       # End index for current subtrahend

                            # Apply crosses for the current subtrahend
                            for i in range(start_cross_idx, end_cross_idx):
                                row = i // cols
                                col = i % cols
                                item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                                item_y = y + BOX_PADDING / 2 + row * (ITEM_SIZE + ITEM_PADDING)

                                # Draw horizontal line of the cross
                                line1 = etree.Element(
                                    "line",
                                    x1=str(item_x),
                                    y1=str(item_y),
                                    x2=str(item_x + ITEM_SIZE),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line1)

                                # Draw vertical line of the cross
                                line2 = etree.Element(
                                    "line",
                                    x1=str(item_x + ITEM_SIZE),
                                    y1=str(item_y),
                                    x2=str(item_x),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line2)

                        if unittrans_unit:
                            # Define circle position
                            circle_radius = 30
                            # circle_center_x = item_x + ITEM_SIZE -5 
                            circle_center_x = item_x + ITEM_SIZE/2
                            circle_center_y = item_y - circle_radius # Above the top-right corner of the item

                            # Add purple circle
                            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                                            r=str(circle_radius), fill="#BBA7F4")


                            unittrans_text = f"{unittrans_value}"

                            text_element = etree.SubElement(svg_root, "text",
                                                            x=str(circle_center_x-15), #
                                                            y=str(circle_center_y + 5),  # Center text vertically
                                                            style="font-size: 15px;",
                                                            text_anchor="middle",  # Center align text
                                                            dominant_baseline="middle")  # Center align text vertically
                            text_element.text = unittrans_text


            


        # Draw containers
        for entity in containers:  # Assuming exactly two containers
            print("entity: ", entity)
            draw_entity(entity)
        
        # Draw operator
       
        operator_svg_mapping = {
            "surplus": "division",  # Map 'surplus' to 'subtraction.svg'
            "default": "addition"      # Fallback default operator
        }
    








        # Update SVG size
        final_width = max_x + MARGIN
        final_height = max_y + MARGIN + 50
        svg_root.attrib["width"] = str(final_width)
        svg_root.attrib["height"] = str(final_height)

        # Draw big box
        if len(containers) > 1:
            big_box_x = 20 # Add padding on the left
            big_box_y = 80  # Start above the figures and text
            big_box_width = max_x + 2* MARGIN - 80# Add padding on the right
            big_box_height = max_y + 2* MARGIN - 90 # Extend below the smaller boxes
            
            # Embed text and figures at the top of the big box
            # result_container = result_containers[-1]
            container_entity = original_containers[0]
            embed_top_figures_and_text(svg_root, big_box_x, big_box_y, big_box_width, container_entity['container_type'], container_entity['container_name'], container_entity['attr_type'], container_entity['attr_name'])

            etree.SubElement(svg_root, "rect", x=str(big_box_x), y=str(big_box_y), width=str(big_box_width),
                            height=str(big_box_height), stroke="black", fill="none", stroke_width="2")
            
            # Update SVG size
            final_width = max_x + 2* MARGIN
            final_height = max_y + 2*  MARGIN + 50
            svg_root.attrib["width"] = str(final_width)
            svg_root.attrib["height"] = str(final_height)

            e = containers[-1]
            # print('e.get("subtrahend_entity_quantity", 0) > 20',e.get("subtrahend_entity_quantity", 0) )
            

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            # Add a purple circle at the top-right corner of the big box--for division is different!!
            circle_radius = 30
            circle_center_x = x + w
            circle_center_y = y + h
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?" 
            # + result_containers[-1]['entity_name']
            # Save the combined SVG
            # Adjust SVG canvas size dynamically (including the circle)
            svg_padding = 20  # Optional padding for the edges
            circle_extra_space = circle_radius * 2  # Ensure the circle is fully included
        return True, str(float(svg_root.attrib["width"]) - start_x), str(float(svg_root.attrib["height"]) - MARGIN + 15)
        
    def handle_area(operations, containers, svg_root, resources_path, result_containers,start_x = 100,start_y = 100):
        global error_message
        print("Handling area")
        
        if len(containers) != 2:
            error_message = "Area calculation requires exactly two containers (length, width), requirements do not met."
            print("Area calculation requires exactly two containers (length, width).")
            return

        # 1. Extract length and width
        length_entity = containers[0]
        width_entity = containers[1]
        length = length_entity["item"].get("entity_quantity", 0)
        width = width_entity["item"].get("entity_quantity", 0)

        # 2. Extract shape info from result_containers[0]
        if not result_containers:
            error_message = "No result_containers provided for the shape."
            print("No result_containers provided for the shape.")
            return
        result_e = result_containers[0]
        container_type = result_e.get("container_type", "").strip()  
        container_name = result_e.get("container_name", "").strip()

        # 3. Basic constants
        UNIT_SIZE = 40
        MARGIN = 50

        # 4. Helper to track bounding box for the final SVG
        max_x, max_y = 0, 0
        def update_max_dimensions(x_val, y_val):
            nonlocal max_x, max_y
            if x_val > max_x:
                max_x = x_val
            if y_val > max_y:
                max_y = y_val

        # 5. Helper to embed an SVG file
  
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
            root.attrib["preserveAspectRatio"] = "none"
            update_max_dimensions(x + width, y + height)
            return root
        # 6. Helper to construct the path to the shape SVG
        def get_figure_svg_path(name):
            if name:
                return os.path.join(resources_path, f"{name}.svg")
            return None

        # 7. Calculate aspect ratio and dimensions
        # Target display size
        max_display_size = 300  # Adjust this as needed
        aspect_ratio = length / width if width != 0 else 1  # Avoid division by zero
        if aspect_ratio > 1:  # Wider than tall
            shape_display_width = max_display_size
            shape_display_height = max_display_size / aspect_ratio
        else:  # Taller than wide
            shape_display_height = max_display_size
            shape_display_width = max_display_size * aspect_ratio

        # 8. Position the shape
        shape_x = start_x
        shape_y = start_y

        # 9. Load and display the shape SVG
        shape_path = get_figure_svg_path(container_type)
        clean_shape_path = get_figure_svg_path(container_type + "_clean")
        if shape_path and os.path.exists(shape_path):
            remove_svg_blanks(shape_path, clean_shape_path)
            print('shape_display_width', shape_display_width)
            print('shape_display_height', shape_display_height)
            shape_svg = embed_svg(clean_shape_path, shape_x, shape_y, 
                                shape_display_width, shape_display_height)
            svg_root.append(shape_svg)
        else:
            # If the SVG does not exist, draw an orange rectangle
            print(f"No valid SVG found for container_type = '{container_type}'. Drawing an orange box instead.")
            rectangle = etree.SubElement(svg_root, "rect",
                                        x=str(shape_x),
                                        y=str(shape_y),
                                        width=str(shape_display_width),
                                        height=str(shape_display_height),
                                        fill="orange",
                                        stroke="black",
                                        stroke_width="2")
        update_max_dimensions(shape_x + shape_display_width, shape_y + shape_display_height)
        # 10. Place text for length and width
        length = float(length)
        width = float(width)
        if length.is_integer():
            length_str = str(int(length))
        else:
            length_str = str(length)
        
        if width.is_integer():
            width_str = str(int(width))
        else:
            width_str = str(width)
        

        #container name at top-center
        container_text_x = shape_x + shape_display_width / 2
        container_text_y = shape_y - 10 - 40
        container_text_el = etree.SubElement(svg_root, "text", 
                                        x=str(container_text_x),
                                        y=str(container_text_y),
                                        style="font-size: 20px; text-anchor: middle;")
        container_text_el.text = f"{container_name}"

        # Length at lower top-center
        length_text_x = shape_x + shape_display_width / 2
        length_text_y = shape_y - 10
        length_text_el = etree.SubElement(svg_root, "text", 
                                        x=str(length_text_x),
                                        y=str(length_text_y),
                                        style="font-size: 20px; text-anchor: middle;")
        length_text_el.text = f"{length_str}"

        # Width at left-center
        width_text_x = shape_x - 35
        width_text_y = shape_y + shape_display_height / 2
        width_text_el = etree.SubElement(svg_root, "text",
                                        x=str(width_text_x),
                                        y=str(width_text_y),
                                        style="font-size: 20px; text-anchor: end; dominant-baseline: middle;")
        width_text_el.text = f"{width_str}"


        # handle unittrans
        length_unittrans_unit = length_entity.get("unittrans_unit", "")
        length_unittrans_value = length_entity.get("unittrans_value", "")
        # length_unittrans_value = length_unittrans_value * length
        width_unittrans_unit = width_entity.get("unittrans_unit", "")
        width_unittrans_value = width_entity.get("unittrans_value", "")
        # width_unittrans_value = width_unittrans_value * width

        if length_unittrans_value:
            # Define circle position
            circle_radius = 30
            unit_trans_padding = 50
            circle_center_x = length_text_x
            circle_center_y = length_text_y - circle_radius - 20 

            # Add purple circle
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                            r=str(circle_radius), fill="#BBA7F4")

            unittrans_text = f"{length_unittrans_value}"

            text_element = etree.SubElement(svg_root, "text",
                                            x=str(circle_center_x-20), 
                                            y=str(circle_center_y + 5),  # Center text vertically
                                            style="font-size: 15px;",
                                            text_anchor="middle",  # Center align text
                                            dominant_baseline="middle")  # Center align text vertically
            text_element.text = unittrans_text
        
        if width_unittrans_value:
            # Define circle position
            circle_radius = 30
            unit_trans_padding = 50
            circle_center_x = width_text_x
            circle_center_y = width_text_y - circle_radius - 20 

            # Add purple circle
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y),
                            r=str(circle_radius), fill="#BBA7F4")
            unittrans_text = f"{width_unittrans_value}"
            text_element = etree.SubElement(svg_root, "text",
                                            x=str(circle_center_x-20),
                                            y=str(circle_center_y + 5),  # Center text vertically
                                            style="font-size: 15px;",
                                            text_anchor="middle",  # Center align text
                                            dominant_baseline="middle")  # Center align text vertically
            text_element.text = unittrans_text


        # Update bounding box for text
        update_max_dimensions(length_text_x, length_text_y)
        update_max_dimensions(width_text_x, width_text_y)

        # 11. Set overall SVG canvas size
        final_width = max_x + MARGIN
        final_height = max_y + MARGIN
        svg_root.attrib["width"] = str(final_width)
        svg_root.attrib["height"] = str(final_height)
        return True, str(float(svg_root.attrib["width"]) - start_x), str(float(svg_root.attrib["height"]) - MARGIN + 15)
        
       
    def handle_tvq_final(operations, containers, svg_root, resources_path, result_containers,start_x = 50,start_y = 150):
        global error_message
        print("Handling tvq_final")
        # Constants
        UNIT_SIZE = 40
        APPLE_SCALE = 0.75
        ITEM_SIZE = int(UNIT_SIZE * APPLE_SCALE)
        ITEM_PADDING = int(UNIT_SIZE * 0.25)
        BOX_PADDING = UNIT_SIZE
        OPERATOR_SIZE = 30
        MAX_ITEM_DISPLAY = 10
        MARGIN = 50
        if any("unittrans_unit" in entity for entity in containers):
            ITEM_SIZE = 3 * ITEM_SIZE

        original_containers = containers  # keep a copy

        addition_containers = []
        subtrahend_containers = []
        subtraction_index = []

        # We also keep track of the latest "addition_entity" index:
        current_addition_index = None

        # The first entity in 'containers' presumably belongs to the first operation
        # or stands alone before any operation. We treat it as an addition by default:
        addition_containers.append(containers[0])
        current_addition_index = 0  # index in the addition_containers list

        # 1) Separate out addition vs. subtraction containers
        for i, operation in enumerate(operations):
            # 'i' aligns with the operator index in 'operations',
            # so 'containers[i+1]' is the entity that comes after that operator.
            the_entity = containers[i + 1]

            if operation['entity_type'] == "addition":
                addition_containers.append(the_entity)
                current_addition_index = len(addition_containers) - 1

            elif operation['entity_type'] == "subtraction":
                # Optionally record which addition entity preceded it
                the_entity["subtract_from_addition_index"] = current_addition_index

                # This entity is a subtrahend
                subtrahend_containers.append(the_entity)
                subtraction_index.append(i)

            else:
                error_message = f"Unsupported operation: {operation}"
                print(f"Unsupported operation: {operation}")
                return

        # A list of colors for successive subtraction operations
        cross_colors = ["black", "red", "blue", "yellow", "green", 
                        "purple", "orange", "pink", "brown", "grey"]

        addition_containers = []
        subtrahend_containers = []
        subtraction_index = []

        # We keep track of the latest addition index
        current_addition_index = None

        # The first entity is considered an addition by default
        addition_containers.append(containers[0])
        current_addition_index = 0

        # 1) Separate out addition vs. subtraction
        for i, operation in enumerate(operations):
            the_entity = containers[i + 1]  # This is the entity after the i-th operation
            if operation['entity_type'] == "addition":
                addition_containers.append(the_entity)
                current_addition_index = len(addition_containers) - 1
            elif operation['entity_type'] == "subtraction":
                subtrahend_containers.append(the_entity)
                subtraction_index.append(i)
                the_entity["subtract_from_addition_index"] = current_addition_index
            else:
                error_message = f"Unsupported operation: {operation}"
                print(f"Unsupported operation: {operation}")
                return

        print("Before allocation:")
        print("addition_containers:", addition_containers)
        print("subtrahend_containers:", subtrahend_containers)

        # 2) Initialize a list to track subtractions on each addition entity
        for a_ent in addition_containers:
            # Instead of a single number, we track a list of subtractions
            # each item can have structure: {"entity_quantity": X, "color": Y}
            a_ent["subtrahend_entity_quantity"] = []

        # 3) Allocate each subtrahend's entity_quantity among matching addition containers
        #    Also assign a unique color to each subtrahend (subtraction operation).
        for idx, s_ent in enumerate(subtrahend_containers):
            s_entity_type = s_ent["item"]["entity_type"]
            s_qty_to_allocate = s_ent["item"]["entity_quantity"]
            temp_entity_quantity = float(s_qty_to_allocate)
            if not temp_entity_quantity.is_integer():
                error_message = "Cannot generate INTUITIVE visual because the subtrahend entity_quantity is not an integer"
                print("Cannot generate INTUITIVE visual because the subtrahend entity_quantity is not an integer")
                return
            addition_index = s_ent["subtract_from_addition_index"]
            # Assign color to this subtraction operation
            current_subtraction_color = cross_colors[idx % len(cross_colors)]
            s_ent["color"] = current_subtraction_color

            # Walk from the most recent addition entity backward
            # for j in reversed(range(len(addition_containers))):
            for j in reversed(range(addition_index + 1)):
                a_ent = addition_containers[j]

                # Only match if entity_types align
                if a_ent["item"]["entity_type"] == s_entity_type:
                    addition_total = a_ent["item"]["entity_quantity"]
                    # sum of all subtractions so far for this addition
                    already_subtracted = sum(sub["entity_quantity"] for sub in a_ent["subtrahend_entity_quantity"])
                    available = addition_total - already_subtracted

                    if available <= 0:
                        continue

                    if available >= s_qty_to_allocate:
                        # This addition entity can cover the entire subtrahend
                        a_ent["subtrahend_entity_quantity"].append({
                            "entity_quantity": s_qty_to_allocate,
                            "color": current_subtraction_color
                        })
                        s_qty_to_allocate = 0
                        break  # done allocating
                    else:
                        # Use as much as possible here
                        a_ent["subtrahend_entity_quantity"].append({
                            "entity_quantity": available,
                            "color": current_subtraction_color
                        })
                        s_qty_to_allocate -= available

                if s_qty_to_allocate == 0:
                    break

            # If s_qty_to_allocate > 0 after this loop, we ran out of additions 
            # to match. You can handle leftover if needed.

        print("\nAfter allocation:")
        print("addition_containers:", addition_containers)
        print("subtrahend_containers:", subtrahend_containers)

        # 4) Final check: If an addition entity has subtractions AND entity_quantity > 10 => print message
        for a_ent in addition_containers:
            # If there's anything in a_ent["subtractions"], it participated in a subtraction
            if a_ent["subtrahend_entity_quantity"] and a_ent["item"]["entity_quantity"] > 10: #
                error_message = "Cannot generate INTUITIVE visual because the minuend entity_quantity higher than 10"
                print("Cannot generate INTUITIVE visual because the minuend entity_quantity higher than 10")
                return
 
        for a_ent in subtrahend_containers:
            # If there's anything in a_ent["subtractions"], it participated in a subtraction
            if a_ent["item"]["entity_quantity"] > 10:
                error_message = "Cannot generate INTUITIVE visual because the subtrahend entity_quantity higher than 10"
                print("Cannot generate INTUITIVE visual because the subtrahend entity_quantity higher than 10")
                return
        # If desired, set 'containers' to just the addition_containers
        containers = addition_containers        



        # Extract quantities and entity_types
        quantities = [e["item"].get("entity_quantity", 0) for e in containers]
        entity_types = [e["item"].get("entity_type", "") for e in containers]

        any_multiplier = any(t == "multiplier" for t in entity_types)
        any_above_20 = any(q > MAX_ITEM_DISPLAY for q in quantities)

        # Determine entity layout entity_type first
        for e in containers:
            q = e["item"].get("entity_quantity", 0)
            t = e["item"].get("entity_type", "")
            container = e.get("container_type", "")
            attr = e.get("attr_type", "")

            
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

        # Focus on normal layout containers
        normal_container = [e for e in containers if e["layout"] == "normal"]

        # Compute global layout for normal containers:
        # 1. Find the largest entity_quantity among normal layout containers
        if normal_container:
            largest_normal_q = max(e["item"].get("entity_quantity",0) for e in normal_container)
        else:
            largest_normal_q = 1

        # 2. Compute global max_cols and max_rows for this largest normal q
        if largest_normal_q > 0:
            max_cols = int(math.ceil(math.sqrt(largest_normal_q)))
            max_rows = (largest_normal_q + max_cols - 1) // max_cols
        else:
            max_cols, max_rows = 1, 1

        # Assign these global cols and rows to all normal containers
        for e in normal_container:
            e["cols"] = max_cols
            e["rows"] = max_rows

        # For row/column containers and large containers, compute cols/rows individually
        unit_trans_padding = 0
        for e in containers:
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
        # large_total_width = text_width + 10 + UNIT_SIZE + 10 + UNIT_SIZE  #
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

        for e in containers:
            w,h = compute_entity_box_size(e)
            e["planned_width"] = w
            if e.get("unittrans_unit", ""):
                e["planned_height"] = h + 50
            else:
                e["planned_height"] = h

            # print('e["planned_width"]', e["planned_width"])
            # print('e["planned_height"]', e["planned_height"])


        # Position planning 
        # start_x, start_y = 50, 150
        operator_gap = e_gap = eq_gap = qmark_gap = 20

        # Initialize the starting point for the first entity
        current_x = start_x
        current_y = start_y
        box_y = start_y
        # Iterate through the containers and operators
        for i, entity in enumerate(containers):
            # Set position for the current entity
            entity["planned_x"] = current_x
            # if entity.get("unittrans_unit", ""):
            #     entity["planned_y"] = current_y 
            #     entity["planned_box_y"] = current_y - 50
            #     box_y = current_y - 50
            # else:
            entity["planned_y"] = current_y
            entity["planned_box_y"] = current_y
            box_y = current_y

            # Update the rightmost x-coordinate of the current entity
            e_right = current_x + entity["planned_width"]
            if i < len(operations):
                # Position the operator
                operator_x = e_right + operator_gap
                operator_y = box_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2)
                operations[i]["planned_x"] = operator_x
                operations[i]["planned_y"] = operator_y

                # Update the x-coordinate for the next entity
                current_x = operator_x + OPERATOR_SIZE + e_gap
            else:
                # For the last entity, just update the x-coordinate for spacing
                current_x = e_right + e_gap
        # Position the equals sign
        eq_x = current_x + eq_gap
        eq_y = box_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2)
        # Position the question mark
        qmark_x = eq_x + 30 + qmark_gap
        qmark_y = box_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2)-15






        max_x, max_y = 0,0
        def update_max_dimensions(x_val, y_val):
            nonlocal max_x, max_y
            if x_val > max_x:
                max_x = x_val
            if y_val > max_y:
                max_y = y_val

       
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
        
        def get_figure_svg_path(attr_type):
            if attr_type:
                return os.path.join(resources_path, f"{attr_type}.svg")
            return None

    
        def embed_top_figures_and_text(parent, box_x, box_y, box_width, container_type, container_name, attr_type, attr_name):
            print("calling embed_top_figures_and_text")
            items = []
            show_something = container_name or container_type or attr_name or attr_type
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

                if attr_type and attr_name:
                    figure_path = get_figure_svg_path(attr_type)
                    if figure_path and os.path.exists(figure_path):
                        items.append(("svg", attr_type))
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
            attr_type = e.get("attr_type", "").strip()

            # UnitTrans-specific attributes
            unittrans_unit = e.get("unittrans_unit", "")
            unittrans_value = e.get("unittrans_value", "")

            subtrahend_name = e.get("subtrahend_name", "")
            subtrahend_entity_type = e.get("subtrahend_entity_type", "")
            subtrahend_entity_quantity = e.get("subtrahend_entity_quantity", 0)

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            layout = e["layout"]
            cols = e["cols"]
            rows = e["rows"]

            # Adjust box size if unittrans_unit exists
            # if unittrans_unit:
            #     # w += 50  # Increase width to accommodate the circle
            #     h += 50  # Increase height if needed
            q = float(q)
            if layout == "multiplier":
                if q.is_integer():
                    q_str = str(int(q))  # Convert to integer
                else:
                    q_str = str(q)  # Keep as is
                text_x = x
                # Adjust text_y to align with operator
                text_y = start_y + (containers[0]["planned_height"] / 2) - (OPERATOR_SIZE / 2) + 30
                text_element = etree.SubElement(svg_root, "text", x=str(text_x), y=str(text_y),
                                                style="font-size: 50px;", dominant_baseline="middle")
                text_element.text = q_str
                update_max_dimensions(text_x + len(q_str)*30, text_y + 50)
                return
            # Draw box 
            
            etree.SubElement(svg_root, "rect", x=str(x), y=str(box_y),
                            width=str(w), height=str(h), stroke="black", fill="none")
            update_max_dimensions(x + w, y + h)

            
            


            # Embed text or figures at the top
            embed_top_figures_and_text(svg_root, x, box_y, w, container_type, container_name, attr_type, attr_name)


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

                
                # extra vertical space if there's a unittrans
                unit_trans_padding = 50 if unittrans_unit else 0
                svg_y = svg_y + unit_trans_padding
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

                # 1) Precompute which items get crossed, and their colors
                # -------------------------------------------------------
                cross_colors = ["black", "red", "blue", "yellow", "green",
                                "purple", "orange", "pink", "brown", "grey"]

                sub_segments = []  # each entry = {"start": int, "end": int, "color": str}

                remaining_entity_quantity = int(q)
                used_colors = set()

                for idx, sub_info in enumerate(e.get("subtrahend_entity_quantity", [])):
                    # sub_info might have {"entity_quantity": X, "color": Y} or similar
                    sub_qty = int(sub_info["entity_quantity"])  # how many items to cross for this subtrahend
                    # pick color from sub_info if it exists, else fallback to cross_colors
                    if "color" in sub_info and sub_info["color"]:
                        color = sub_info["color"]
                    else:
                        # fallback to cross_colors list
                        color = cross_colors[idx] if idx < len(cross_colors) else f"#{''.join(random.choice('0123456789ABCDEF') for _ in range(6))}"
                    while color in used_colors:
                        color = f"#{''.join(random.choice('0123456789ABCDEF') for _ in range(6))}"
                    used_colors.add(color)

                    # compute start/end for this sub-entity_quantity
                    # same logic as before: we look at sum of sub-quantities from idx onward
                    start_cross_idx = remaining_entity_quantity - sum(d["entity_quantity"] for d in e["subtrahend_entity_quantity"][idx:])
                    end_cross_idx = start_cross_idx + sub_qty

                    sub_segments.append({
                        "start": start_cross_idx,
                        "end": end_cross_idx,
                        "color": color
                    })

                print("sub_segments:", sub_segments)
                # 2) Now draw items AND crosses in the same loop
                # ----------------------------------------------
                if layout in ["normal", "row", "column"]:
                    item_svg_path = os.path.join(resources_path, f"{t}.svg")
                    
                    for i in range(int(q)):
                        # figure out row/col
                        row = i // cols
                        col = i % cols

                        # extra vertical space if there's a unittrans
                        unit_trans_padding = 50 if unittrans_unit else 0
                        
                        # compute x,y for item
                        item_x = x + BOX_PADDING / 2 + col * (ITEM_SIZE + ITEM_PADDING)
                        if row == 0:
                            item_y = y + BOX_PADDING / 2 + unit_trans_padding
                        else:
                            item_y = (y + BOX_PADDING / 2 
                                    + row * (ITEM_SIZE + ITEM_PADDING + unit_trans_padding) 
                                    + unit_trans_padding)

                        # draw the item
                        svg_root.append(embed_svg(item_svg_path, x=item_x, y=item_y, width=ITEM_SIZE, height=ITEM_SIZE))

                        # if there's a unittrans, draw the purple circle & text above
                        if unittrans_unit:
                            circle_radius = 30
                            circle_center_x = item_x + ITEM_SIZE/2
                            circle_center_y = item_y - circle_radius
                            etree.SubElement(svg_root, "circle",
                                            cx=str(circle_center_x),
                                            cy=str(circle_center_y),
                                            r=str(circle_radius),
                                            fill="#BBA7F4")
                            text_element = etree.SubElement(svg_root, "text",
                                                            x=str(circle_center_x - 15),
                                                            y=str(circle_center_y + 5),
                                                            style="font-size: 15px;",
                                                            text_anchor="middle",
                                                            dominant_baseline="middle")
                            text_element.text = f"{unittrans_value}"

                        # 3) Check sub_segments to see if item 'i' should be crossed
                        # ----------------------------------------------------------
                        for seg in sub_segments:
                            if seg["start"] <= i < seg["end"]:
                                color = seg["color"]

                                # draw 2 diagonal lines
                                line1 = etree.Element(
                                    "line",
                                    x1=str(item_x),
                                    y1=str(item_y),
                                    x2=str(item_x + ITEM_SIZE),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line1)

                                line2 = etree.Element(
                                    "line",
                                    x1=str(item_x + ITEM_SIZE),
                                    y1=str(item_y),
                                    x2=str(item_x),
                                    y2=str(item_y + ITEM_SIZE),
                                    style=f"stroke:{color}; stroke-width:2;"
                                )
                                svg_root.append(line2)

            


        # Draw containers
        for entity in containers:  # Assuming exactly two containers
            print("entity: ", entity)
            draw_entity(entity)
        
   
        operator_svg_mapping = {
            "surplus": "division",  # Map 'surplus' to 'subtraction.svg'
            "default": "addition"      # Fallback default operator
        }
    








        # Update SVG size
        final_width = max_x + MARGIN
        final_height = max_y + MARGIN + 50
        svg_root.attrib["width"] = str(final_width)
        svg_root.attrib["height"] = str(final_height)

        # Draw big box
        if len(containers) > 1:
            big_box_x = start_x - 30 # Add padding on the left
            big_box_y = start_y - 70  # Start above the figures and text
            big_box_width = max_x + 2* MARGIN - 80 - (start_x - 50)# Add padding on the right
            big_box_height = max_y + 2* MARGIN - 90 # Extend below the smaller boxes

            # Embed text and figures at the top of the big box
            result_container = result_containers[-1]
            embed_top_figures_and_text(svg_root, big_box_x, big_box_y, big_box_width, result_container['container_type'], result_container['container_name'], result_container['attr_type'], result_container['attr_name'])
            
            etree.SubElement(svg_root, "rect", x=str(big_box_x), y=str(big_box_y), width=str(big_box_width),
                            height=str(big_box_height), stroke="black", fill="none", stroke_width="2")
            
            # Update SVG size
            final_width = max_x + 2* MARGIN
            final_height = max_y + 2*  MARGIN + 50
            svg_root.attrib["width"] = str(final_width)
            svg_root.attrib["height"] = str(final_height)

            # Add a purple circle at the bottom-right corner of the big box
            circle_radius = 30
            circle_center_x = big_box_x + big_box_width
            circle_center_y = big_box_y + big_box_height
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?"
            # Save the combined SVG
            # Adjust SVG canvas size dynamically (including the circle)
            svg_padding = 20  # Optional padding for the edges
            circle_extra_space = circle_radius * 2  # Ensure the circle is fully included
        else:
            e = containers[0]
            # print('e.get("subtrahend_entity_quantity", 0) > 20',e.get("subtrahend_entity_quantity", 0) )
            

            x = e["planned_x"]
            y = e["planned_y"]
            box_y = e["planned_box_y"]
            w = e["planned_width"]
            h = e["planned_height"]
            # Add a purple circle at the bottom-right corner of the big box
            circle_radius = 30
            circle_center_x = x + w
            circle_center_y = y + h
            etree.SubElement(svg_root, "circle", cx=str(circle_center_x), cy=str(circle_center_y), r=str(circle_radius),
                            fill="#BBA7F4")

            # Add red text "?" inside the circle
            # Add red text "?" inside the circle
            text_element = etree.SubElement(svg_root, "text", 
                                            x=str(circle_center_x-6),  # Horizontal center of the circle
                                            y=str(circle_center_y+6),  # Vertical center of the circle
                                            style="font-size: 30px;",  # Explicit font size
                                            text_anchor="middle",  # Horizontal alignment
                                            fill="red", 
                                            dominant_baseline="central")  # Vertical alignment
            text_element.text = "?"
            # Save the combined SVG
            # Adjust SVG canvas size dynamically (including the circle)
            svg_padding = 20  # Optional padding for the edges
            circle_extra_space = circle_radius * 2  # Ensure the circle is fully included
        return True, str(float(svg_root.attrib["width"]) - start_x), str(float(svg_root.attrib["height"]) - MARGIN + 15)
        
        
    def handle_comparison(
        compare1_operations, compare1_containers, compare1_result_containers,
        compare2_operations, compare2_containers, compare2_result_containers,
        svg_root,
        resources_path,
        start_x=50,
        start_y=150):

        print("Handling comparison start")

        # We will store bounding boxes: (x, y, width, height) for each side
        entity_boxes = [None, None]

        # We'll iterate over the two "compare sides"
        comp_op_list = [compare1_operations, compare2_operations]
        comp_entity_list = [compare1_containers, compare2_containers]
        comp_result_container_list = [compare1_result_containers, compare2_result_containers]

        current_x = start_x
        current_y = start_y

        for i in range(2):
            operations_i = comp_op_list[i]
            containers_i = comp_entity_list[i]
            result_i = comp_result_container_list[i]
            svg_width = 0
            svg_height = 0

            if all(op["entity_type"] in ["addition", "subtraction"] for op in operations_i):
                print("Handling tvq_final")
                try:
                    created, w, h = handle_tvq_final(operations_i,containers_i,svg_root,resources_path,result_i,start_x=current_x,start_y=current_y)
                except:
                    return
                svg_width, svg_height = int(float(w)), int(float(h))
            elif all(op["entity_type"] == "multiplication" for op in operations_i) and len(operations_i) == 1:
                print("Handling multiplication")
                try:
                    created, w, h = handle_multiplication(
                    operations_i,
                    containers_i,
                    svg_root,
                    resources_path,
                    result_i,
                    start_x=current_x,
                    start_y=current_y)
                except:
                    return
                svg_width, svg_height = int(float(w)), int(float(h))
            elif all(op["entity_type"] == "division" for op in operations_i) and len(operations_i) == 1:
                print("Handling division")
                try:
                    created, w, h = handle_division(
                    operations_i,
                    containers_i,
                    svg_root,
                    resources_path,
                    result_i,
                    start_x=current_x,
                    start_y=current_y)
                except:
                    return
                svg_width, svg_height = int(float(w)), int(float(h))
            elif all(op["entity_type"] == "surplus" for op in operations_i) and len(operations_i) == 1:
                print("Handling surplus")
                try:
                    created, w, h = handle_surplus(
                        operations_i,
                        containers_i,
                        svg_root,
                        resources_path,
                        result_i,
                        start_x=current_x,
                        start_y=current_y)
                except:
                    return
                svg_width, svg_height = int(float(w)), int(float(h))
            elif all(op["entity_type"] == "area" for op in operations_i) and len(operations_i) == 1:
                print("Handling area")
                try:
                    created, w, h = handle_area(
                        operations_i,
                        containers_i,
                        svg_root,
                        resources_path,
                        result_i,
                        start_x=current_x,
                        start_y=current_y)
                except:
                    return
                svg_width, svg_height = int(float(w)), int(float(h))
            elif all(op["entity_type"] in ["addition", "subtraction"] for op in operations_i):
                print("Handling tvq_final (mixed add/sub)")
                try:
                    created, w, h = handle_tvq_final(
                    operations_i,
                    containers_i,
                    svg_root,
                    resources_path,
                    result_i,
                    start_x=current_x,
                    start_y=current_y)
                except:
                    return
                svg_width, svg_height = int(float(w)), int(float(h))
            entity_boxes[i] = (current_x, current_y, svg_width, svg_height)

            current_x += svg_width + 110  # spacing

        # draw balance scale
        draw_balance_scale(svg_root, entity_boxes)

        # return True, str(float(svg_root.attrib["width"]) - start_x), str(float(svg_root.attrib["height"]) - MARGIN + 15)
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
        # svg_root.attrib["width"] =  str(float(svg_root.attrib["width"]) + 20)
        # svg_root.attrib["height"] = str((base_y + base_height - bottom_of_figures) + float(svg_root.attrib["height"]) + 20)
        svg_root.attrib["height"] = str(base_y + base_height + 20)
        

  




    # main function:
    created = False
    if data.get('operation') == "comparison":
        (
        compare1_operations, 
        compare1_containers, 
        compare1_result_containers,
        compare2_operations, 
        compare2_containers, 
        compare2_result_containers
        ) = extract_operations_and_containers_for_comparison(data)

        # if find container_name of different entity are different but the container entity_type are the same, update the second entity's container entity_type to be original entity_type-2,the third to be original entity_type-3...
        compare1_containers,compare1_result_containers = update_container_types_optimized(compare1_containers, compare1_result_containers)
        #if the last result_container share the same container_name with any entity, update the container_name of result_container.
        if compare1_result_containers and compare1_containers: 
            # [e.update({'container_name': '', 'container_type': ''}) for e in compare1_containers if e.get('container_name') == compare1_result_containers[-1].get('container_name')]
            last_container = compare1_result_containers[-1].get('container_name')
            if any(e.get('container_name') == last_container for e in compare1_containers) and last_container:
                compare1_result_containers[-1]['container_name'] = f"{last_container} (result)"
        

        
        # if find container_name of different entity are different but the container entity_type are the same, update the second entity's container entity_type to be original entity_type-2,the third to be original entity_type-3...
        compare2_containers,compare2_result_containers = update_container_types_optimized(compare2_containers, compare2_result_containers)
        if compare2_result_containers and compare2_containers: 
            # [e.update({'container_name': '', 'container_type': ''}) for e in compare1_containers if e.get('container_name') == compare1_result_containers[-1].get('container_name')]
            last_container = compare2_result_containers[-1].get('container_name')
            if any(e.get('container_name') == last_container for e in compare2_containers) and last_container:
                compare2_result_containers[-1]['container_name'] = f"{last_container} (result)"


        # compare1_operations = compare1_operations[::-1]
        # compare2_operations = compare2_operations[::-1]
        compare1_operations = [{"entity_type": op} for op in compare1_operations]
        compare2_operations = [{"entity_type": op} for op in compare2_operations]
        print(f"compare 1 operations: {compare1_operations}")
        print(f"compare 1 containers: {compare1_containers}")
        print(f"compare 1 result containers: {compare1_result_containers}")

        print(f"compare 2 operations: {compare2_operations}")
        print(f"compare 2 containers: {compare2_containers}")
        print(f"compare 2 result containers: {compare2_result_containers}")
        try:
            created, svg_width, svg_height = handle_comparison(compare1_operations, compare1_containers, compare1_result_containers,
                          compare2_operations, compare2_containers, compare2_result_containers,
                          svg_root,resources_path)
        except Exception as e:
            print("Error in handle_comparison: ",e)
            error_message = "Error in handle_comparison"
            created = False
    else:
        operations, containers, result_containers = extract_operations_and_containers(data)

        # if result_containers and containers: 
        #     [e.update({'container_name': '', 'container_type': ''}) for e in containers if e.get('container_name') == result_containers[-1].get('container_name')]

        # if find container_name of different entity are different but the container entity_type are the same, update the second entity's container entity_type to be original entity_type-2,the third to be original entity_type-3...
  
        containers,result_containers = update_container_types_optimized(containers, result_containers)
        #if the last result_container share the same container_name with any entity, update the container_name of result_container.
        if result_containers and containers: 
            # [e.update({'container_name': '', 'container_type': ''}) for e in compare1_containers if e.get('container_name') == compare1_result_containers[-1].get('container_name')]
            last_container = result_containers[-1].get('container_name')
            if any(e.get('container_name') == last_container for e in containers) and last_container:
                result_containers[-1]['container_name'] = f"{last_container} (result)"



        # operations = operations[::-1]
        operations = [{"entity_type": op} for op in operations]
        print(f"Operations: {operations}")
        print(f"containers: {containers}")
        print(f"Result containers: {result_containers}")

        if all(op["entity_type"] in ["addition", "subtraction"] for op in operations):
            print("Handling tvq_final")
            try:
                created, svg_width, svg_height = handle_tvq_final(operations, containers, svg_root, resources_path,result_containers)
            except:
                created = False
        elif all(op["entity_type"] == "multiplication" for op in operations) and len(operations) == 1:
            print("Handling multiplication")
            try:
                created, svg_width, svg_height = handle_multiplication(operations, containers, svg_root, resources_path,result_containers)
            except:
                created = False
        elif all(op["entity_type"] == "division" for op in operations) and len(operations) == 1:
            print("Handling division")
            try:
                created, svg_width, svg_height = handle_division(operations, containers, svg_root, resources_path,result_containers)
            except:
                created = False
        elif all(op["entity_type"] == "surplus" for op in operations) and len(operations) == 1:
            print("Handling surplus")
            try:
                created, svg_width, svg_height = handle_surplus(operations, containers, svg_root, resources_path,result_containers)
            except:
                created = False
        elif all(op["entity_type"] == "area" for op in operations) and len(operations) == 1:
            print("Handling area")
            try:
                created, svg_width, svg_height = handle_area(operations, containers, svg_root, resources_path,result_containers)
            except:
                created = False
        # this is for tvq_final, if all op contain and only contain addition and subtraction, it is tvq_final
        elif all(op["entity_type"] in ["addition", "subtraction"] for op in operations):
            print("Handling tvq_final")
            try:
                created, svg_width, svg_height = handle_tvq_final(operations, containers, svg_root, resources_path,result_containers)
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
    output_dir = os.path.join(current_dir, 'output_visual_intuitive')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, '01.svg')
    svg_dataset = os.path.join(current_dir, 'svg_dataset')
    visual_language = ["surplus(container1[entity_name: gingerbread cookie, entity_type: gingerbread-cookie, entity_quantity: 10, container_name: home, container_type: home, attr_name: , attr_type: ], container2[entity_name: gingerbread cookie, entity_type: gingerbread-cookie, entity_quantity: 3, container_name: tiny glass jar, container_type: jar, attr_name:, attr_type: ], result_entity[entity_name: gingerbread cookie, entity_type: gingerbread-cookie, entity_quantity: 1, container_name: unplaced cookies, container_type: remainder, attr_name: , attr_type: ])"]
    data = parse_dsl(visual_language[0])
    # data = "{'operation': 'subtraction', 'entities': [{'name': 'container1', 'item': {'entity_type': 'apple', 'entity_quantity': 3.0}, 'entity_name': 'apple', 'container_name': 'Lucy', 'container_type': 'girl', 'attr_name': 'initial', 'attr_type': 'count', 'layout': 'normal', 'cols': 2, 'rows': 2.0, 'planned_width': 120, 'planned_height': 120.0, 'planned_x': 50, 'planned_y': 100, 'planned_box_y': 100}, {'name': 'container2', 'item': {'entity_type': 'apple', 'entity_quantity': 1.0}, 'entity_name': 'apple', 'container_name': 'Mike', 'container_type': 'boy', 'attr_name': 'given', 'attr_type': 'transaction', 'layout': 'normal', 'cols': 2, 'rows': 2.0, 'planned_width': 120, 'planned_height': 120.0, 'planned_x': 240, 'planned_y': 100, 'planned_box_y': 100}, {'name': 'result_entity', 'item': {'entity_type': 'apple', 'entity_quantity': 2.0}, 'entity_name': 'apple', 'container_name': 'Lucy', 'container_type': 'girl', 'attr_name': 'remaining', 'attr_type': 'count'}]}"
    render_svgs_from_data(output_path, svg_dataset, data)
