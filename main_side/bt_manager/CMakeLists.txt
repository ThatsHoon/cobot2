cmake_minimum_required(VERSION 3.8)
project(bt_manager)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(behaviortree_cpp_v3 REQUIRED)
find_package(rclcpp_action REQUIRED)
find_package(nlohmann_json REQUIRED)
find_package(command REQUIRED)
find_package(std_msgs REQUIRED)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  # the following line skips the linter which checks for copyrights
  # comment the line when a copyright and license is added to all source files
  set(ament_cmake_copyright_FOUND TRUE)
  # the following line skips cpplint (only works in a git repo)
  # comment the line when this package is in a git repo and when
  # a copyright and license is added to all source files
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

add_executable(bt_manager
  src/main.cpp
  # src/PickItemNode.cpp (나중에 cpp 파일을 분리한다면 여기에 추가)
)
ament_target_dependencies(bt_manager rclcpp behaviortree_cpp_v3 rclcpp_action command nlohmann_json std_msgs)

install(TARGETS
  bt_manager
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()
install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}
)
